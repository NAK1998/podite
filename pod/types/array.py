from .atomic import U32
from ..bytes import BYTES_CATALOG
from .._utils import _GetitemToCall, get_concrete_type, get_calling_module
from ..json import JSON_CATALOG
from ..decorators import pod


def _fixed_len_array(name, type_, length):
    module = get_calling_module()

    @pod(dataclass_fn=None)
    class _ArrayPod:
        @classmethod
        def _is_static(cls) -> bool:
            return BYTES_CATALOG.is_static(get_concrete_type(module, type_))

        @classmethod
        def _calc_max_size(cls):
            return (
                    BYTES_CATALOG.calc_max_size(get_concrete_type(module, type_)) * length
            )

        @classmethod
        def _from_bytes_partial(cls, buffer):
            result = []
            for _ in range(length):
                value = BYTES_CATALOG.unpack_partial(
                    get_concrete_type(module, type_), buffer
                )
                result.append(value)

            return result

        @classmethod
        def _to_bytes_partial(cls, obj, buffer):
            for elem in obj:
                BYTES_CATALOG.pack_partial(
                    get_concrete_type(module, type_), buffer, elem
                )

        @classmethod
        def _to_dict(cls, obj):
            return [
                JSON_CATALOG.pack(get_concrete_type(module, type_), e) for e in obj
            ]

        @classmethod
        def _from_dict(cls, raw):
            return [
                JSON_CATALOG.unpack(get_concrete_type(module, type_), e) for e in raw
            ]

    _ArrayPod.__name__ = f"{name}[{type_}, {length}]"
    _ArrayPod.__qualname__ = _ArrayPod.__name__

    return _ArrayPod


def _fixed_len_bytes(name, length):
    @pod(dataclass_fn=None)
    class _BytesPod:
        @classmethod
        def _is_static(cls) -> bool:
            return True

        @classmethod
        def _calc_max_size(cls):
            return length

        @classmethod
        def _from_bytes_partial(cls, buffer):
            return buffer.read(length)

        @classmethod
        def _to_bytes_partial(cls, obj, buffer):
            buffer.write(obj.ljust(length, b"\x00"))

        @classmethod
        def _to_dict(cls, obj):
            return list(obj)

        @classmethod
        def _from_dict(cls, raw):
            return bytes(raw)

        @classmethod
        def _to_dict(cls, obj):
            return list(obj)

        @classmethod
        def _from_dict(cls, raw):
            return bytes(raw)

    _BytesPod.__name__ = f"{name}[{length}]"
    _BytesPod.__qualname__ = _BytesPod.__name__

    return _BytesPod


def _fixed_len_str(name, length, encoding="UTF-8", autopad=True):
    @pod(dataclass_fn=None)
    class _StrPod:
        @classmethod
        def _is_static(cls) -> bool:
            return True

        @classmethod
        def _calc_max_size(cls):
            return length

        @classmethod
        def _from_bytes_partial(cls, buffer):
            encoded = buffer.read(length)

            if autopad:
                last = 0
                while last < len(encoded) and encoded[last] != 0:
                    last += 1
                encoded = encoded[:last]

            return encoded.decode(encoding)

        @classmethod
        def _to_bytes_partial(cls, obj, buffer):
            encoded = obj.encode(encoding)
            if len(encoded) > length:
                raise ValueError("len(value) > length")
            elif len(encoded) < length and not autopad:
                raise ValueError("len(value) < size")

            buffer.write(encoded.ljust(length, b"\x00"))

        @classmethod
        def _to_dict(cls, obj):
            return obj

        @classmethod
        def _from_dict(cls, raw):
            return raw

    _StrPod.__name__ = f"{name}[{length}, encoding={encoding}]"
    _StrPod.__qualname__ = _StrPod.__name__

    return _StrPod


def _var_len_array(name, type_, max_length=None, length_type=None):
    module = get_calling_module()

    if length_type is None:
        length_type = U32

    if max_length is None:
        max_length = 2 ** BYTES_CATALOG.calc_max_size(length_type)

    @pod(dataclass_fn=None)
    class _ArrayPod:
        @classmethod
        def is_static(cls) -> bool:
            return False

        @classmethod
        def _calc_max_size(cls):
            len_size = BYTES_CATALOG.calc_max_size(length_type)
            body_size = (
                    BYTES_CATALOG.calc_max_size(get_concrete_type(module, type_))
                    * max_length
            )
            return len_size + body_size

        @classmethod
        def _from_bytes_partial(cls, buffer):
            length = BYTES_CATALOG.unpack_partial(length_type, buffer)
            if length > max_length:
                raise RuntimeError("actual_length > max_length")

            result = []
            for _ in range(length):
                value = BYTES_CATALOG.unpack_partial(
                    get_concrete_type(module, type_), buffer
                )
                result.append(value)

            return result

        @classmethod
        def _to_bytes_partial(cls, obj, buffer):
            if len(obj) > max_length:
                raise RuntimeError("actual_length > max_length")

            BYTES_CATALOG.pack_partial(length_type, buffer, len(obj))
            for elem in obj:
                BYTES_CATALOG.pack_partial(
                    get_concrete_type(module, type_), buffer, elem
                )

        @classmethod
        def _to_dict(cls, obj):
            return [
                JSON_CATALOG.pack(get_concrete_type(module, type_), e) for e in obj
            ]

        @classmethod
        def _from_dict(cls, raw):
            return [
                JSON_CATALOG.unpack(get_concrete_type(module, type_), e) for e in raw
            ]

    _ArrayPod.__name__ = (
        f"{name}[{type_}, length_type={length_type}, max_length={max_length}]"
    )
    _ArrayPod.__qualname__ = _ArrayPod.__name__

    return _ArrayPod


def _var_len_bytes(name, max_length=None, length_type=None):
    if length_type is None:
        length_type = U32

    if max_length is None:
        max_length = 2 ** BYTES_CATALOG.calc_max_size(length_type)

    @pod(dataclass_fn=None)
    class _BytesPod:
        @classmethod
        def _is_static(cls) -> bool:
            return False

        @classmethod
        def _calc_max_size(cls):
            len_size = BYTES_CATALOG.calc_max_size(length_type)
            body_size = max_length
            return len_size + body_size

        @classmethod
        def _from_bytes_partial(cls, buffer):
            length = BYTES_CATALOG.unpack_partial(length_type, buffer)
            if length > max_length:
                raise RuntimeError("actual_length > max_length")

            return buffer.read(length)

        @classmethod
        def _to_bytes_partial(cls, obj, buffer):
            if len(obj) > max_length:
                raise RuntimeError("actual_length > max_length")

            BYTES_CATALOG.pack_partial(length_type, buffer, len(obj))
            buffer.write(obj)

        @classmethod
        def _to_dict(cls, obj):
            return list(obj)

        @classmethod
        def _from_dict(cls, raw):
            return bytes(raw)

    _BytesPod.__name__ = f"{name}[length_type={length_type}, max_length={max_length}]"
    _BytesPod.__qualname__ = _BytesPod.__name__

    return _BytesPod


def _var_len_str(name, max_length=None, length_type=None, encoding="UTF-8"):
    if length_type is None:
        length_type = U32

    if max_length is None:
        max_length = 2 ** BYTES_CATALOG.calc_max_size(length_type)

    @pod(dataclass_fn=None)
    class _StrPod:
        @classmethod
        def _is_static(cls) -> bool:
            return False

        @classmethod
        def _calc_max_size(cls):
            len_size = BYTES_CATALOG.calc_max_size(length_type)
            body_size = max_length
            return len_size + body_size

        @classmethod
        def _from_bytes_partial(cls, buffer):
            length = BYTES_CATALOG.unpack_partial(length_type, buffer)
            if length > max_length:
                raise RuntimeError("actual_length > max_length")

            return buffer.read(length).decode(encoding)

        @classmethod
        def _to_bytes_partial(cls, obj, buffer):
            if len(obj) > max_length:
                raise RuntimeError("actual_length > max_length")

            BYTES_CATALOG.pack_partial(length_type, buffer, len(obj))
            buffer.write(obj.encode(encoding))

        @classmethod
        def _to_dict(cls, obj):
            return obj

        @classmethod
        def _from_dict(cls, raw):
            return raw

    _StrPod.__name__ = f"{name}[max_length={max_length}, length_type={length_type}, encoding={encoding}]"
    _StrPod.__qualname__ = _StrPod.__name__

    return _StrPod


FixedLenArray = _GetitemToCall("FixedLenArray", _fixed_len_array)
FixedLenBytes = _GetitemToCall("FixedLenBytes", _fixed_len_bytes)
FixedLenStr = _GetitemToCall("FixedLenStr", _fixed_len_str)

Vec = _GetitemToCall("Vec", _var_len_array)
Bytes = _GetitemToCall("Bytes", _var_len_bytes)
Str = _GetitemToCall("Str", _var_len_str)


def register_arrays():
    BYTES_CATALOG.register(_var_len_str.)