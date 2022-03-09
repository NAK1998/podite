from abc import ABC, abstractmethod
from dataclasses import is_dataclass, fields, dataclass
from io import BytesIO
from typing import Tuple, Dict, Any, Literal
from .errors import PodPathError
from .core import PodConverterCatalog, POD_SELF_CONVERTER
from ._utils import FORMAT_BORSCH, FORMAT_PASS, FORMAT_AUTO, FORMAT_ZERO_COPY

class BytesPodConverter(ABC):
    @abstractmethod
    def is_static(self, type_) -> bool:
        raise NotImplementedError

    @abstractmethod
    def calc_max_size(self, type_) -> int:
        raise NotImplementedError

    @abstractmethod
    def pack_partial(self, type_, buffer, obj, **kwargs) -> Any:
        raise NotImplementedError

    @abstractmethod
    def unpack_partial(self, type_, buffer, **kwargs) -> Any:
        raise NotImplementedError


IS_STATIC = "_is_static"
CALC_MAX_SIZE = "_calc_max_size"
TO_BYTES_PARTIAL = "_to_bytes_partial"
FROM_BYTES_PARTIAL = "_from_bytes_partial"


def dataclass_is_static(cls) -> bool:
    for field in fields(cls):
        if not BYTES_CATALOG.is_static(cls._get_field_type(field.type)):
            return False
    return True


def dataclass_calc_max_size(cls):
    total = 0
    for field in fields(cls):
        total += BYTES_CATALOG.calc_max_size(cls._get_field_type(field.type))

    return total


def dataclass_to_bytes_partial(cls, buffer, obj, **kwargs):
    for field in fields(cls):
        value = None
        try:
            value = getattr(obj, field.name)
            BYTES_CATALOG.pack_partial(cls._get_field_type(field.type), buffer, value, **kwargs)
        except PodPathError as e:
            e.path.append(field.name)
            e.path.append(cls.__name__)
            raise
        except Exception as e:
            raise PodPathError("Failed to serialize dataclass", [field.name, cls.__name__], field.type.__name__, value) from e


def dataclass_from_bytes_partial(cls, buffer, **kwargs):
    values = {}
    for field in fields(cls):
        try:
            values[field.name] = BYTES_CATALOG.unpack_partial(
                cls._get_field_type(field.type), buffer, **kwargs
            )
        except PodPathError as e:
            e.path.append(field.name)
            e.path.append(cls.__name__)
            raise
        except Exception as e:
            raise PodPathError("Failed to deserialize dataclass", [field.name, cls.__name__], field.type.__name__) from e
    return cls(**values)


class SelfBytesPodConverter(BytesPodConverter):
    def get_mapping(self, type_):
        converters = getattr(type_, POD_SELF_CONVERTER, ())
        if "bytes" in converters:
            return self
        return None

    def is_static(self, type_) -> bool:
        return getattr(type_, IS_STATIC)()

    def calc_max_size(self, type_) -> int:
        return getattr(type_, CALC_MAX_SIZE)()

    def pack_partial(self, type_, buffer, obj, **kwargs) -> Any:
        return getattr(type_, TO_BYTES_PARTIAL)(buffer, obj, **kwargs)

    def unpack_partial(self, type_, buffer, **kwargs) -> Any:
        return getattr(type_, FROM_BYTES_PARTIAL)(buffer, **kwargs)


class AutoTagTypeValueManager:
    def __init__(self, tag_type):
        self._tag_type = tag_type

    def __enter__(self):
        self.old = AutoTagType.TAG_TYPE[0]
        AutoTagType.TAG_TYPE[0] = self._tag_type

    def __exit__(self, exc_type, exc_val, exc_tb):
        AutoTagType.TAG_TYPE[0] = self.old


@dataclass(init=False)
class AutoTagType:
    TAG_TYPE = [None]  # mutable static var

    @classmethod
    def _is_static(cls) -> bool:
        return False

    @classmethod
    def _calc_max_size(cls):
        ty = AutoTagType.TAG_TYPE[0]
        print("_calc_max_size", ty)
        val_size = BYTES_CATALOG.calc_max_size(ty)
        return val_size

    @classmethod
    def _to_bytes_partial(cls, buffer, obj, **kwargs):
        print("_to_bytes_partial")
        BYTES_CATALOG.pack_partial(AutoTagType.TAG_TYPE[0], buffer, obj, **kwargs)

    @classmethod
    def _from_bytes_partial(cls, buffer: BytesIO, **kwargs):
        return BYTES_CATALOG.unpack_partial(AutoTagType.TAG_TYPE[0], buffer, **kwargs)

    @classmethod
    def _to_dict(cls, obj):
        return obj

    @classmethod
    def _from_dict(cls, obj):
        return obj


# register that AutoTagType knows how to convert itself to bytes
setattr(AutoTagType, POD_SELF_CONVERTER, ["bytes"])


class BytesPodConverterCatalog(PodConverterCatalog[BytesPodConverter]):
    def is_static(self, type_):
        """
        Unpacks obj according to given type_ by trying all registered converters.
        """
        error_msg = "No converter was able to answer if this obj is static"
        converter = self._get_converter_or_raise(type_, error_msg)
        return converter.is_static(type_)

    def calc_max_size(self, type_):
        """
        Unpacks obj according to given type_ by trying all registered converters.
        """
        error_msg = f"No converter was able to calculate maximum size of type {type_}"
        converter = self._get_converter_or_raise(type_, error_msg)
        return converter.calc_max_size(type_)

    def pack(self, type_, obj, format=FORMAT_BORSCH, **kwargs):
        buffer = BytesIO()
        self.pack_partial(type_, buffer, obj, format=format, **kwargs)

        return buffer.getvalue()

    def pack_partial(self, type_, buffer, obj, format=FORMAT_BORSCH, **kwargs):
        from pod.types import U8, U64
        error_msg = "No converter was able to pack raw data"
        converter = self._get_converter_or_raise(type_, error_msg)
        if format == FORMAT_BORSCH:
            tag_type = U8
        elif format == FORMAT_PASS:
            return converter.pack_partial(type_, buffer, obj, format=format, **kwargs)
        elif format == FORMAT_ZERO_COPY:
            tag_type = U64
        else:
            raise ValueError(f'Format argument must be {FORMAT_AUTO}, {FORMAT_BORSCH}, or {FORMAT_ZERO_COPY}, found {format}')

        with AutoTagTypeValueManager(tag_type):
            return converter.pack_partial(type_, buffer, obj, format=format, **kwargs)

    def unpack(self, type_, raw, checked=False, format=FORMAT_AUTO, **kwargs) -> object:
        buffer = BytesIO(raw)
        obj = self.unpack_partial(type_, buffer, format=format, **kwargs)

        if checked and buffer.tell() < len(buffer.getvalue()):
            raise RuntimeError("Unused bytes in provided raw data")

        return obj

    def unpack_partial(self, type_, buffer, format=FORMAT_AUTO, **kwargs) -> Tuple[bool, object]:
        print(self, type_, buffer)
        error_msg = "No converter was able to unpack object"
        converter = self._get_converter_or_raise(type_, error_msg)

        if format == FORMAT_AUTO:
            from pod.types import U64
            with AutoTagTypeValueManager(U64):
                pos = buffer.tell()
                buffer.seek(0, 2)
                if converter.calc_max_size(type_) == buffer.tell():
                    format = FORMAT_ZERO_COPY
                else:
                    format = FORMAT_BORSCH
                buffer.seek(pos)

        if format == FORMAT_BORSCH:
            from pod.types import U8
            tag_type = U8
        elif format == FORMAT_ZERO_COPY:
            from pod.types import U64
            tag_type = U64
        elif format == FORMAT_PASS:
            return converter.unpack_partial(type_, buffer, format=format, **kwargs)
        else:
            raise ValueError(f'Format argument must be {FORMAT_AUTO}, {FORMAT_BORSCH}, or {FORMAT_ZERO_COPY}, found {format}')

        with AutoTagTypeValueManager(tag_type):
            return converter.unpack_partial(type_, buffer, format=format, **kwargs)

    def generate_helpers(self, type_) -> Dict[str, classmethod]:
        helpers = super().generate_helpers(type_)

        def is_static(cls):
            return BYTES_CATALOG.is_static(cls)

        def calc_max_size(cls):
            return BYTES_CATALOG.calc_max_size(cls)

        def calc_size(cls):
            if not cls.is_static():
                raise RuntimeError("calc_size can only be called for static classes")

            return cls.calc_max_size()

        def to_bytes(cls, obj, **kwargs):
            return cls.pack(obj, converter="bytes", **kwargs)

        def from_bytes(cls, raw, format=FORMAT_AUTO, **kwargs):
            print("in from_bytes")
            return cls.unpack(raw, converter="bytes", format=format, **kwargs)

        helpers.update(
            {
                "is_static": classmethod(is_static),
                "calc_max_size": classmethod(calc_max_size),
                "calc_size": classmethod(calc_size),
                "to_bytes": classmethod(to_bytes),
                "from_bytes": classmethod(from_bytes),
            }
        )

        if is_dataclass(type_):
            helpers.update(self._generate_packers())

        return helpers

    @staticmethod
    def _generate_packers() -> Dict[str, classmethod]:
        return {
            IS_STATIC: classmethod(dataclass_is_static),
            CALC_MAX_SIZE: classmethod(dataclass_calc_max_size),
            TO_BYTES_PARTIAL: classmethod(dataclass_to_bytes_partial),
            FROM_BYTES_PARTIAL: classmethod(dataclass_from_bytes_partial),
        }


BYTES_CATALOG = BytesPodConverterCatalog()
BYTES_CATALOG.register(SelfBytesPodConverter().get_mapping)
