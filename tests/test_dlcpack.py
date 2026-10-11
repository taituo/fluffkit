"""Tests for dlcpack and the A18 pipeline.

Run:  python3 -m unittest discover -s tests -v

- Synthetic tests always run.
- Tests on the real base DLC run when it is cached (~/.cache/fluffkit/tu003410.dlc,
  created by `fluffkit.py pack`) or FLUFFKIT_BASE_DLC points to it.
- Codec tests run when a1800_codec is available (bin/, a1800/target/release, PATH, A1800_CODEC).
"""
import hashlib
import math
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dlcpack import APL_END, DLC, SLOTS  # noqa: E402

BASE_SHA256 = "efe11a82a7f837ebd8ab7a76e5873e0be4a0aa23ccedc73cb9c4601139c8e203"


def make_dlc(sections: dict[str, bytes]) -> bytes:
    slots = [None, "PAL", "SPR", "CEL", "XLS", None, None, None, None, "AMF", "APL", "LPS", "SEQ", "MTR", None, None]
    hdr = "FURBY".encode("utf-16-le").ljust(32, b"\0") + bytes.fromhex("7856341202000800")
    counter = 0x0040CFB5
    for name in slots:
        if name and name in sections:
            e = "DLC_0000.".encode("utf-16-le") + name.encode("utf-16-le") + b"\0\0"
            e += struct.pack("<III", counter, len(sections[name]), 0)
            counter += 0x1A
        else:
            e = b"\0" * 38
        hdr += e
    assert len(hdr) == 0x288
    return hdr + b"".join(sections[n] for n in slots if n and n in sections)


def amf(tracks):
    return DLC._build_amf(tracks)


def track(nframes, fill=0x11):
    return struct.pack("<IH", nframes * 40 + 2, 16000) + bytes([fill]) * (nframes * 40)


def base_dlc_path():
    p = os.environ.get("FLUFFKIT_BASE_DLC") or str(Path.home() / ".cache" / "fluffkit" / "tu003410.dlc")
    return Path(p) if Path(p).exists() else None


class SyntheticDLC(unittest.TestCase):
    def setUp(self):
        self.tracks = [track(3, 1), track(5, 2), track(1, 3)]
        self.pls = [[0, 0x1032, 1, APL_END], [2, APL_END]]
        self.data = make_dlc({"PAL": b"\x01" * 128, "AMF": amf(self.tracks),
                              "APL": DLC._build_apl(self.pls), "MTR": b"\x02" * 10})

    def test_roundtrip(self):
        self.assertEqual(DLC(self.data).build(), self.data)

    def test_parse(self):
        d = DLC(self.data)
        self.assertEqual(d.order, ["PAL", "AMF", "APL", "MTR"])
        self.assertEqual(d.tracks, self.tracks)
        self.assertEqual(d.playlists, self.pls)
        self.assertEqual(d.audio_for(0), [0, 1])

    def test_set_phrase_and_sizes(self):
        d = DLC(self.data)
        d.set_phrase(0, 1, track(50, 9))
        out = DLC(d.build())
        self.assertEqual(out.playlists[0], [1, APL_END])
        self.assertEqual(out.tracks[1], track(50, 9))
        self.assertEqual(out.raw["PAL"], b"\x01" * 128)
        self.assertEqual(out.raw["MTR"], b"\x02" * 10)

    def test_minify(self):
        d = DLC(self.data)
        d.minify_audio(80)
        self.assertEqual(d.tracks[1], struct.pack("<IH", 82, 16000) + b"\x02" * 80)
        self.assertEqual(d.tracks[2], track(1, 3))  # shorter than 80 bytes: unchanged

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            DLC(b"\0" * 0x300)


@unittest.skipUnless(base_dlc_path(), "base DLC not cached (run fluffkit.py pack once)")
class BaseDLC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = base_dlc_path().read_bytes()
        assert hashlib.sha256(cls.data).hexdigest() == BASE_SHA256

    def test_roundtrip_byte_identical(self):
        self.assertEqual(DLC(self.data).build(), self.data)

    def test_layout(self):
        d = DLC(self.data)
        self.assertEqual(d.order, ["PAL", "SPR", "CEL", "XLS", "AMF", "APL", "LPS", "SEQ", "MTR"])
        self.assertEqual(len(d.tracks), 146)
        for t in d.tracks:
            ln, br = struct.unpack("<IH", t[:6])
            self.assertEqual(br, 16000)
            self.assertEqual((ln - 2) % 40, 0)

    def test_slot_table_matches_playlists(self):
        d = DLC(self.data)
        self.assertEqual(len(SLOTS), 60)
        self.assertEqual(len({apl for _, apl, _ in SLOTS}), 60)
        for code, apl, trk in SLOTS:
            self.assertEqual(code[0], 75)
            self.assertEqual(d.audio_for(apl)[0], trk)

    def test_pack_changes_only_amf_apl(self):
        d = DLC(self.data)
        d.minify_audio(128)
        for _, apl, trk in SLOTS[:10]:
            d.set_phrase(apl, trk, track(25))
        out = DLC(d.build())
        orig = DLC(self.data)
        for name in orig.order:
            if name not in ("AMF", "APL"):
                self.assertEqual(out.raw[name], orig.raw[name], name)


def codec_available():
    try:
        import fluffkit
        fluffkit.codec_bin()
        return True
    except SystemExit:
        return False
    except Exception:
        return False


@unittest.skipUnless(codec_available(), "a1800_codec not built")
class A18Pipeline(unittest.TestCase):
    def test_encode_layout_and_decode(self):
        import fluffkit
        import wave
        sr, n = 16000, 16000
        pcm = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / sr))) for i in range(n))
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "in.wav"
            with wave.open(str(w), "wb") as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr); f.writeframes(pcm)
            body = fluffkit.encode_a18_body(w)
            ln, br = struct.unpack("<IH", body[:6])
            self.assertEqual(br, 16000)
            self.assertEqual(ln, len(body) - 4)
            self.assertEqual((ln - 2) % 40, 0)
            self.assertEqual((ln - 2) // 40, 50)  # 1 s in -> 50 frames out (pad frame offsets the dropped first frame)
            out = Path(td) / "out.wav"
            fluffkit.decode_body(body, out)
            with wave.open(str(out)) as f:
                dec = f.readframes(f.getnframes())
        a = struct.unpack(f"<{n}h", pcm)
        b = struct.unpack(f"<{len(dec) // 2}h", dec)[:n]
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
        self.assertGreater(dot / (na * nb), 0.9)  # zero-lag correlation: timing matches the DLL


if __name__ == "__main__":
    unittest.main()


class FirmwareAMF(unittest.TestCase):
    def test_amf_layout_same_as_dlc(self):
        import fluffkit
        tracks = [track(3, 1), track(2, 2)]
        other = b"SP62ALP\0" + b"\0" * 20          # a non-A1800 entry, as at the end of personality AMFs
        data = bytearray(DLC._build_amf(tracks + [other]))
        clips = fluffkit.amf_clips(bytes(data))
        self.assertEqual(clips[:2], tracks)
        self.assertIsNone(clips[2])
