"""A lighter copy of an MP4/M4A song for playback: the same audio, without the cover embedded in its header.

Measured 18-11-2026: all 1948 songs in the library carry their cover inside the MP4 header (median 456 KB),
and a player cannot make a sound before it has the whole header. Over a slow path (a Tailscale relay from
a university network carried 25-220 KB/s) that alone meant 5-20 s before the first note -- and the app
already fetches the cover separately. Without it a song needs a median 133 KB instead of 588 KB to start.

Nothing on disk changes. The header (everything before the end of the 'moov' box) is rebuilt in memory
without the 'covr' items; the audio after it is served from the original file, shifted by the bytes
removed, and the chunk offsets in the header ('stco'/'co64') are shifted to match. Anything unexpected
(no cover, audio before the header, fragmented files, offsets pointing inside the header) raises
NotLightened and the caller serves the original file untouched.
"""
import struct
from collections import OrderedDict
from dataclasses import dataclass

# Boxes whose children are searched: the path to the iTunes item list and to the chunk offset tables.
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"meta", b"ilst"}
_MAX_HEADER = 4 * 1024 * 1024


class NotLightened(Exception):
    pass


@dataclass(frozen=True)
class Light:
    header: bytes            # bytes [0, len(header)) of the light file
    original_header_end: int  # the light file continues with the original from here

    @property
    def cut(self) -> int:
        return self.original_header_end - len(self.header)

    def size(self, original_size: int) -> int:
        return original_size - self.cut


@dataclass
class _Box:
    kind: bytes
    large: bool                  # the original used a 64-bit size field
    prefix: bytes = b""          # version/flags of a full box ('meta'), kept as is
    payload: bytes = b""
    children: list | None = None

    def encode(self, cut: int) -> bytes:
        if self.children is not None:
            body = self.prefix + b"".join(child.encode(cut) for child in self.children)
        elif self.kind == b"stco":
            body = _shift(self.payload, 4, cut)
        elif self.kind == b"co64":
            body = _shift(self.payload, 8, cut)
        else:
            body = self.payload
        if self.large or len(body) + 8 > 0xFFFFFFFF:
            return struct.pack(">I4sQ", 1, self.kind, len(body) + 16) + body
        return struct.pack(">I4s", len(body) + 8, self.kind) + body


def _shift(payload: bytes, width: int, cut: int) -> bytes:
    if len(payload) < 8:
        raise NotLightened("short offset table")
    count = struct.unpack(">I", payload[4:8])[0]
    if len(payload) != 8 + count * width:
        raise NotLightened("offset table size")
    fmt = f">{count}{'I' if width == 4 else 'Q'}"
    offsets = struct.unpack(fmt, payload[8:])
    return payload[:8] + struct.pack(fmt, *(o - cut for o in offsets))


def _parse(data: bytes, start: int, end: int) -> list[_Box]:
    boxes, pos = [], start
    while pos < end:
        if pos + 8 > end:
            raise NotLightened("truncated box")
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        head, large = 8, False
        if size == 1:
            if pos + 16 > end:
                raise NotLightened("truncated box")
            size, head, large = struct.unpack(">Q", data[pos + 8:pos + 16])[0], 16, True
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            raise NotLightened("box size")
        body_start, body_end = pos + head, pos + size
        if kind in (b"mvex", b"moof"):
            raise NotLightened("fragmented")
        if kind in _CONTAINERS:
            prefix = b""
            # 'meta' is a full box in MP4 files (4 bytes of version/flags before its children) but a
            # plain container in QuickTime ones: tell them apart by where the first child's type is.
            if kind == b"meta" and data[body_start + 4:body_start + 8] != b"hdlr":
                prefix = data[body_start:body_start + 4]
                body_start += 4
            boxes.append(_Box(kind, large, prefix, children=_parse(data, body_start, body_end)))
        else:
            boxes.append(_Box(kind, large, payload=data[body_start:body_end]))
        pos = body_end
    return boxes


def _drop_covers(boxes: list[_Box], inside_ilst: bool = False) -> int:
    dropped = 0
    for box in list(boxes):
        if inside_ilst and box.kind == b"covr":
            boxes.remove(box)
            dropped += 1
        elif box.children is not None:
            dropped += _drop_covers(box.children, box.kind == b"ilst")
    return dropped


def _min_offset(boxes: list[_Box]) -> int | None:
    lowest = None
    for box in boxes:
        if box.children is not None:
            child = _min_offset(box.children)
        elif box.kind in (b"stco", b"co64") and len(box.payload) > 8:
            width = 4 if box.kind == b"stco" else 8
            count = struct.unpack(">I", box.payload[4:8])[0]
            fmt = f">{count}{'I' if width == 4 else 'Q'}"
            child = min(struct.unpack(fmt, box.payload[8:8 + count * width]), default=None)
        else:
            child = None
        if child is not None and (lowest is None or child < lowest):
            lowest = child
    return lowest


def lighten(head: bytes) -> Light:
    """head: the original file from byte 0 to the end of its 'moov' box (see mp4_header_end)."""
    if len(head) > _MAX_HEADER:
        raise NotLightened("header too large")
    pos, moov = 0, None
    while pos + 8 <= len(head):
        size, kind = struct.unpack(">I4s", head[pos:pos + 8])
        if size == 1:
            size = struct.unpack(">Q", head[pos + 8:pos + 16])[0]
        if size < 8:
            raise NotLightened("box size")
        if kind == b"mdat":
            raise NotLightened("audio before header")
        if kind == b"moov":
            moov = (pos, pos + size)
        pos += size
    if moov is None or moov[1] != len(head):
        raise NotLightened("header does not end with moov")
    tree = _parse(head, moov[0], moov[1])
    if not _drop_covers(tree):
        raise NotLightened("no embedded cover")
    rebuilt_len = len(b"".join(box.encode(0) for box in tree))
    cut = (moov[1] - moov[0]) - rebuilt_len
    lowest = _min_offset(tree)
    if lowest is not None and lowest < moov[1]:
        raise NotLightened("chunk offsets inside the header")
    light = head[:moov[0]] + b"".join(box.encode(cut) for box in tree)
    return Light(light, moov[1])


class LightCache:
    """Rebuilt headers by (song, original size): a song is only rebuilt once while it stays here."""

    def __init__(self, max_bytes: int = 48 * 1024 * 1024):
        self.max_bytes = max_bytes
        self._items: OrderedDict = OrderedDict()
        self._bytes = 0

    def get(self, key):
        if key not in self._items:
            return False, None
        self._items.move_to_end(key)
        return True, self._items[key]

    def put(self, key, light: Light | None):
        size = len(light.header) if light else 64
        if key in self._items:
            old = self._items.pop(key)
            self._bytes -= len(old.header) if old else 64
        self._items[key] = light
        self._bytes += size
        while self._bytes > self.max_bytes and self._items:
            _, old = self._items.popitem(last=False)
            self._bytes -= len(old.header) if old else 64
