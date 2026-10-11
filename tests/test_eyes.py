"""Eye animation tests. Format tests always run; injection tests need Pillow and the base DLC."""
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eyes as E  # noqa: E402
from dlcpack import DLC, SLOTS  # noqa: E402
from test_dlcpack import base_dlc_path  # noqa: E402

try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


class Formats(unittest.TestCase):
    def test_cel_roundtrip(self):
        rnd = random.Random(1)
        px = [rnd.randrange(64) for _ in range(64 * 64)]
        self.assertEqual(E.decode_cel(E.encode_cel(px)), px)
        self.assertEqual(len(E.encode_cel(px)), E.CEL_BYTES)

    def test_rgb555(self):
        self.assertEqual(E.rgb555(255, 255, 255), 0x7FFF)
        self.assertEqual(E.rgb555(0, 0, 0, transparent=True), 0x8000)
        self.assertEqual(E.from555(0x7C00), (248, 0, 0, 255))

    def test_seq_roundtrip_and_marking(self):
        seqs = [[0x3000, 0x4550, 0xC402, 0x8096, 0x116D, 0x8096, 0], [0x2000, 0x454D, 0xE002, 0x10D2, 0x8080, 0]]
        raw = E.build_seq(seqs)
        self.assertEqual(E.parse_seq(raw), seqs)
        self.assertEqual(E.with_custom_eyes(seqs[0]), [0x3000, 0x4550, 0xC402, 0x8401, 0])  # = Context IS demo form
        self.assertEqual(E.with_custom_eyes(seqs[1]), [0x2000, 0x454D, 0xE002, 0x8401, 0])

    def test_apl_to_seq_covers_slots(self):
        self.assertEqual({apl for _, apl, _ in SLOTS}, set(E.APL_TO_SEQ))


@unittest.skipUnless(HAVE_PIL and base_dlc_path(), "needs Pillow and the cached base DLC")
class Inject(unittest.TestCase):
    def frames(self, td, n=4):
        from PIL import Image, ImageDraw
        paths = []
        for i in range(n):
            im = Image.new("RGB", (128, 128), (255, 250, 240))
            d = ImageDraw.Draw(im)
            d.ellipse((24 + 6 * i, 24, 104 + 6 * i, 104), fill=(30, 140, 255))
            d.ellipse((50 + 6 * i, 50, 78 + 6 * i, 78), fill=(10, 10, 10))
            p = Path(td) / f"f{i}.png"
            im.save(p)
            paths.append(str(p))
        return paths

    def test_inject_verify_by_reparse(self):
        base = base_dlc_path().read_bytes()
        D = DLC(base)
        with tempfile.TemporaryDirectory() as td:
            info = E.inject(D, self.frames(td), None)
        _, apl, _ = SLOTS[15]
        E.mark_phrase(D, apl)
        data = D.build()
        R = DLC(data)
        self.assertEqual(R.build(), data)
        spr = E.Sprites(R.raw["SPR"])
        for name, pl, ref, pal_i in (("left", 13, E.LEFT_REF, 4), ("right", 12, E.RIGHT_REF, 5)):
            n = info[name]["frames"]
            self.assertEqual(n, 4)
            for k, off in enumerate(spr.playlists[pl]):
                w = spr.frame(off)
                want = E.quarters(info[name]["index_frames"][min(n - 1, k * n // len(spr.playlists[pl]))])
                for q in range(4):
                    cel = w[2 * q]
                    self.assertEqual(w[2 * q + 1], ref)
                    self.assertEqual(E.decode_cel(R.raw["CEL"][cel * 3072:(cel + 1) * 3072]), want[q])
            self.assertEqual(E.parse_pal(R.raw["PAL"])[pal_i], [E.rgb555(*c) for c in info[name]["palette"]])
        for pl in E.BLANK_PLAYLISTS:
            for off in spr.playlists[pl]:
                self.assertEqual(spr.frame(off)[:8], [1, E.BASE_REF] * 4)
        seqs, stock = E.parse_seq(R.raw["SEQ"]), E.parse_seq(DLC(base).raw["SEQ"])
        changed = [i for i, (a, b) in enumerate(zip(seqs, stock)) if a != b]
        self.assertEqual(changed, [E.APL_TO_SEQ[apl]])
        self.assertEqual(seqs[changed[0]][-2:], [E.EYE_ANIM_WORD, 0])
        # untouched sections
        for name in ("XLS", "LPS", "MTR"):
            self.assertEqual(R.raw[name], DLC(base).raw[name])


if __name__ == "__main__":
    unittest.main()
