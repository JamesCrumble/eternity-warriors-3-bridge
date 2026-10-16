"""The BSON dialect of Glu's client (CoreLib.Serialization.Bson).

Standard BSON tags; the client maps document keys onto C# auto-properties by
name and stores the decoded value as-is, so a value has to arrive with the tag
its property type expects (int32 for int, int64 for long, double for
float/double, string for enums, UTC date in milliseconds for DateTime).
`encode_as` therefore encodes against the class schema from
server/generated/gluon_schema.json; `encode_any` is for `object`-typed values.
"""
import datetime
import struct

T_DOUBLE, T_STRING, T_OBJECT, T_ARRAY, T_BINARY = 1, 2, 3, 4, 5
T_BOOL, T_DATE, T_NULL, T_INT32, T_INT64 = 8, 9, 10, 16, 18

EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


# ---- decoding ---------------------------------------------------------------

def _cstring(b, i):
    j = b.index(b"\0", i)
    return b[i:j].decode("utf-8", "replace"), j + 1


def _value(tag, b, i):
    if tag == T_DOUBLE:
        return struct.unpack_from("<d", b, i)[0], i + 8
    if tag == T_STRING:
        n = struct.unpack_from("<i", b, i)[0]
        return b[i + 4:i + 3 + n].decode("utf-8", "replace"), i + 4 + n
    if tag in (T_OBJECT, T_ARRAY):
        n = struct.unpack_from("<i", b, i)[0]
        d = _document(b, i)
        return (list(d.values()) if tag == T_ARRAY else d), i + n
    if tag == T_BINARY:
        n = struct.unpack_from("<i", b, i)[0]
        return bytes(b[i + 5:i + 5 + n]), i + 5 + n
    if tag == T_BOOL:
        return b[i] != 0, i + 1
    if tag == T_DATE:
        ms = struct.unpack_from("<q", b, i)[0]
        return EPOCH + datetime.timedelta(milliseconds=ms), i + 8
    if tag == T_NULL:
        return None, i
    if tag == T_INT32:
        return struct.unpack_from("<i", b, i)[0], i + 4
    if tag == T_INT64:
        return struct.unpack_from("<q", b, i)[0], i + 8
    raise ValueError("unknown BSON tag %d" % tag)


def _document(b, i):
    end = i + struct.unpack_from("<i", b, i)[0]
    i += 4
    out = {}
    while i < end:
        tag = b[i]
        i += 1
        if tag == 0:
            break
        key, i = _cstring(b, i)
        out[key], i = _value(tag, b, i)
    return out


def decode(b):
    return _document(b, 0)


# ---- encoding ---------------------------------------------------------------

class Int64(int):
    """Marks an `object`-typed value that must go out as int64."""


def _doc(items):
    body = b"".join(items) + b"\0"
    return struct.pack("<i", len(body) + 4) + body


def _elem(tag, key, payload):
    return bytes([tag]) + key.encode() + b"\0" + payload


def _str(s):
    e = s.encode("utf-8")
    return struct.pack("<i", len(e) + 1) + e + b"\0"


def _date_ms(v):
    if isinstance(v, (int, float)):
        return int(v)
    if v.tzinfo is None:
        v = v.replace(tzinfo=datetime.timezone.utc)
    return int((v - EPOCH).total_seconds() * 1000)


def encode_any_elem(key, v):
    if v is None:
        return _elem(T_NULL, key, b"")
    if isinstance(v, bool):
        return _elem(T_BOOL, key, b"\1" if v else b"\0")
    if isinstance(v, Int64):
        return _elem(T_INT64, key, struct.pack("<q", v))
    if isinstance(v, int):
        if -2**31 <= v < 2**31:
            return _elem(T_INT32, key, struct.pack("<i", v))
        return _elem(T_INT64, key, struct.pack("<q", v))
    if isinstance(v, float):
        return _elem(T_DOUBLE, key, struct.pack("<d", v))
    if isinstance(v, str):
        return _elem(T_STRING, key, _str(v))
    if isinstance(v, (bytes, bytearray)):
        return _elem(T_BINARY, key, struct.pack("<i", len(v)) + b"\0" + bytes(v))
    if isinstance(v, datetime.datetime):
        return _elem(T_DATE, key, struct.pack("<q", _date_ms(v)))
    if isinstance(v, (list, tuple)):
        return _elem(T_ARRAY, key, _doc([encode_any_elem(str(i), x) for i, x in enumerate(v)]))
    if isinstance(v, dict):
        return _elem(T_OBJECT, key, _doc([encode_any_elem(k, x) for k, x in v.items()]))
    raise TypeError("cannot encode %r" % (v,))


class Schema:
    def __init__(self, data):
        self.classes = data["classes"]
        self.enums = data["enums"]
        self.codes = data["codes"]
        self.code_of = {v: k for k, v in self.codes.items()}

    def props(self, cls):
        out = {}
        while cls and cls in self.classes:
            c = self.classes[cls]
            for k, t in c["props"].items():
                out.setdefault(k, t)
            cls = c["base"]
        return out

    def _typed_elem(self, key, ctype, v):
        t = ctype.rstrip("?")
        if v is None:
            return _elem(T_NULL, key, b"")
        if t in ("int", "short", "byte", "uint"):
            return _elem(T_INT32, key, struct.pack("<i", int(v)))
        if t in ("long", "ulong"):
            return _elem(T_INT64, key, struct.pack("<q", int(v)))
        if t in ("float", "double"):
            return _elem(T_DOUBLE, key, struct.pack("<d", float(v)))
        if t == "bool":
            return _elem(T_BOOL, key, b"\1" if v else b"\0")
        if t == "string":
            return _elem(T_STRING, key, _str(str(v)))
        if t == "DateTime":
            return _elem(T_DATE, key, struct.pack("<q", _date_ms(v)))
        if t in ("byte[]",):
            return _elem(T_BINARY, key, struct.pack("<i", len(v)) + b"\0" + bytes(v))
        if t in self.enums:
            return _elem(T_STRING, key, _str(str(v)))
        inner = None
        if t.startswith(("List<", "IList<")) and t.endswith(">"):
            inner = t[t.index("<") + 1:-1]
        elif t.endswith("[]"):
            inner = t[:-2]
        if inner is not None:
            return _elem(T_ARRAY, key, _doc([self._typed_elem(str(i), inner, x) for i, x in enumerate(v)]))
        if t in self.classes:
            return _elem(T_OBJECT, key, self.encode_as(t, v))
        return encode_any_elem(key, v)   # object, Dictionary<...>, unknown

    def encode_as(self, cls, obj):
        props = self.props(cls)
        items = []
        for k, v in obj.items():
            if k in props:
                items.append(self._typed_elem(k, props[k], v))
            else:
                items.append(encode_any_elem(k, v))
        return _doc(items)
