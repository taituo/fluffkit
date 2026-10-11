"""
Minimal Furby Connect DLC reader/writer for audio phrase packs.

Only the parts needed to swap audio are parsed (header, AMF audio, APL playlists);
every other section is carried through byte-for-byte.

Format notes (little-endian throughout):

  header (0x288 bytes): 40 magic bytes, then 16 entries of 38 bytes.
    A used entry starts with UTF-16 "DLC_0000." + 3-letter section name;
    bytes 30..34 hold the section length. Sections follow the header in entry order.

  AMF (audio):    u32 count | u32 offset[count] (bytes, from section start) | tracks
                  track = u32 len | u16 bitrate (16000) | A1800 frames (len-2 bytes, 40 B / 20 ms)
  APL (playlists):u16 count | u16 count+0x546 | u32 4 | u32 offset[count] (16-bit words) | entries
                  entry = u16: <0x1000 AMF track index, 0x1xxx pause, 0xF000 end of list

The 60 phrase slots below are the input-75 actions of the base DLC tu003410.dlc
(SHA-256 pinned in fluffkit.py), mapped once from its XLS/SEQ tables:
(action code, playlist index, first audio track).
"""
from __future__ import annotations

import struct

HEADER_LEN = 0x288
MAGIC_LEN = 40
ENTRY_LEN = 38
APL_END = 0xF000

SLOTS: list[tuple[tuple[int, int, int, int], int, int]] = [
    ((75, 0, a, b), apl, trk) for (_, a, b, apl, trk) in [
        (0, 0, 0, 16, 132), (0, 0, 1, 17, 38), (0, 0, 2, 18, 40), (0, 0, 3, 19, 23), (0, 0, 4, 20, 24),
        (0, 0, 5, 21, 41), (0, 0, 6, 22, 27), (0, 0, 7, 23, 34), (0, 1, 0, 0, 33), (0, 1, 1, 1, 71),
        (0, 1, 2, 2, 5), (0, 1, 3, 3, 113), (0, 1, 4, 4, 120), (0, 1, 5, 5, 0), (0, 2, 0, 24, 72),
        (0, 2, 1, 25, 102), (0, 2, 2, 26, 80), (0, 2, 3, 27, 87), (0, 2, 4, 28, 91), (0, 2, 5, 29, 99),
        (0, 2, 6, 30, 7), (0, 2, 7, 31, 105), (0, 3, 0, 32, 125), (0, 3, 1, 33, 51), (0, 3, 2, 34, 32),
        (0, 3, 3, 35, 10), (0, 3, 4, 36, 11), (0, 3, 5, 37, 2), (0, 3, 6, 38, 43), (0, 3, 7, 39, 46),
        (0, 4, 0, 6, 137), (0, 4, 1, 7, 141), (0, 4, 2, 8, 139), (0, 4, 3, 9, 144), (0, 4, 4, 10, 138),
        (0, 4, 5, 11, 142), (0, 4, 6, 12, 145), (0, 4, 7, 13, 143), (0, 5, 0, 40, 48), (0, 5, 1, 41, 64),
        (0, 5, 2, 42, 12), (0, 5, 3, 43, 131), (0, 5, 4, 44, 128), (0, 5, 5, 45, 25), (0, 5, 6, 46, 110),
        (0, 6, 0, 47, 56), (0, 6, 1, 48, 53), (0, 6, 2, 49, 16), (0, 6, 3, 50, 59), (0, 6, 4, 51, 78),
        (0, 6, 5, 52, 124), (0, 6, 6, 53, 127), (0, 7, 0, 54, 22), (0, 7, 1, 55, 68), (0, 7, 2, 14, 140),
        (0, 7, 3, 56, 21), (0, 7, 4, 57, 75), (0, 7, 5, 58, 19), (0, 7, 6, 15, 136), (0, 8, 0, 59, 61),
    ]
]


class DLC:
    def __init__(self, data: bytes):
        if data[:10] != "FURBY".encode("utf-16-le"):
            raise ValueError("not a Furby DLC")
        self.header = bytearray(data[:HEADER_LEN])
        self.order: list[str] = []
        self.entry_pos: dict[str, int] = {}
        self.raw: dict[str, bytes] = {}
        cur = HEADER_LEN
        for i in range(16):
            p = MAGIC_LEN + i * ENTRY_LEN
            e = data[p:p + ENTRY_LEN]
            if e[:18] != "DLC_0000.".encode("utf-16-le"):
                continue
            name = e[18:24:2].decode("ascii")
            size = struct.unpack("<I", e[30:34])[0]
            self.order.append(name)
            self.entry_pos[name] = p
            self.raw[name] = data[cur:cur + size]
            cur += size
        if cur != len(data):
            raise ValueError(f"section sizes ({cur}) do not match file size ({len(data)})")
        self.tracks = self._parse_amf(self.raw["AMF"])
        self.playlists = self._parse_apl(self.raw["APL"])

    @classmethod
    def load(cls, path) -> "DLC":
        with open(path, "rb") as f:
            return cls(f.read())

    # --- AMF
    @staticmethod
    def _parse_amf(b: bytes) -> list[bytes]:
        n = struct.unpack_from("<I", b, 0)[0]
        offs = struct.unpack_from(f"<{n}I", b, 4)
        out = []
        for o in offs:
            ln = struct.unpack_from("<I", b, o)[0]
            out.append(b[o:o + 4 + ln])
        return out

    @staticmethod
    def _build_amf(tracks: list[bytes]) -> bytes:
        off = 4 * (1 + len(tracks))
        offs = []
        for t in tracks:
            offs.append(off)
            off += len(t)
        return struct.pack(f"<I{len(tracks)}I", len(tracks), *offs) + b"".join(tracks)

    # --- APL
    @staticmethod
    def _parse_apl(b: bytes) -> list[list[int]]:
        n, memloc, entry_len = struct.unpack_from("<HHI", b, 0)
        if memloc != n + 0x546 or entry_len != 4:
            raise ValueError("unexpected APL header")
        offs = struct.unpack_from(f"<{n}I", b, 8)
        out = []
        for o in offs:
            p, pl = o * 2, []
            while True:
                w = struct.unpack_from("<H", b, p)[0]
                pl.append(w)
                p += 2
                if w == APL_END:
                    break
            out.append(pl)
        return out

    @staticmethod
    def _build_apl(pls: list[list[int]]) -> bytes:
        n = len(pls)
        off = 2 * (2 + n)  # in 16-bit words
        offs = []
        for pl in pls:
            offs.append(off)
            off += len(pl)
        body = b"".join(struct.pack(f"<{len(pl)}H", *pl) for pl in pls)
        return struct.pack(f"<HHI{n}I", n, n + 0x546, 4, *offs) + body

    # --- edit helpers
    def minify_audio(self, nbytes: int = 128) -> None:
        """Shrink every track to nbytes of frame data (same trick as the Context IS demo)."""
        self.tracks = [struct.pack("<I", nbytes + 2) + t[4:6] + t[6:6 + nbytes]
                       if len(t) - 6 >= nbytes else t for t in self.tracks]

    def set_phrase(self, apl_index: int, track_index: int, track: bytes) -> None:
        self.tracks[track_index] = track
        self.playlists[apl_index] = [track_index, APL_END]

    def audio_for(self, apl_index: int) -> list[int]:
        return [w for w in self.playlists[apl_index] if w < 0x1000]

    def build(self) -> bytes:
        self.raw["AMF"] = self._build_amf(self.tracks)
        self.raw["APL"] = self._build_apl(self.playlists)
        hdr = bytearray(self.header)
        for name in self.order:
            p = self.entry_pos[name]
            hdr[p + 30:p + 34] = struct.pack("<I", len(self.raw[name]))
        return bytes(hdr) + b"".join(self.raw[n] for n in self.order)
