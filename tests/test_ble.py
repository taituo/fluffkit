"""BLE code paths (upload / say) against the real PyFluff library and a simulated Furby.

The simulated Furby lives in tests/fakeble/bleak (a stand-in for the bleak package):
it answers the 0x50 announce with 24 02, collects file writes, and sends 24 05 when
the whole file has arrived. Runs when PyFluff is importable (pip install -e PyFluff,
or PYFLUFF_PATH=/path/to/PyFluff); pydantic is its only extra import here.
"""
import contextlib
import io
import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).resolve().parent / "fakeble"
os.environ["FLUFFKIT_BLE_PACE"] = "0.01"  # the fake Furby answers at once
sys.path.insert(0, str(FAKE))
if os.environ.get("PYFLUFF_PATH"):
    sys.path.insert(1, os.environ["PYFLUFF_PATH"])

try:
    import bleak  # the fake one (first on sys.path)
    import pyfluff.dlc  # noqa: F401
    HAVE = getattr(bleak, "LOG", None) is not None
except Exception:
    HAVE = False


def run(argv, stdin=None):
    old = sys.argv, sys.stdin
    sys.argv = ["fluffkit.py"] + argv
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            runpy.run_path(str(ROOT / "fluffkit.py"), run_name="__main__")
    finally:
        sys.argv, sys.stdin = old
    return out.getvalue()


@unittest.skipUnless(HAVE, "PyFluff not importable")
class BLE(unittest.TestCase):
    def setUp(self):
        bleak.LOG.clear()
        bleak.FILE.clear()
        bleak.SLOTS.clear()
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def gp(self):
        return [d for c, d in bleak.LOG if c == "dab91383" and d != b"\x00"]

    def upload(self, data: bytes, *extra):
        p = self.dir / "my pack.dlc"
        p.write_bytes(data)
        bleak.LOG.clear()
        run(["upload", str(p), "--address", "AA:BB:CC:DD:EE:FF", "--slot", "1", "--timeout", "20", *extra])
        return self.gp()

    def test_upload_activates_the_slot_furby_used(self):
        data = os.urandom(3000)
        cmds = self.upload(data)
        self.assertEqual(bytes(bleak.FILE), data)
        ann = [c for c in cmds if c[0] == 0x50][0]
        self.assertEqual(int.from_bytes(ann[2:5], "big"), 3000)                # size
        self.assertEqual(ann[6:18], b"TU003410.DLC")                           # stock name
        self.assertNotIn(b"\x74\x01", cmds)                                    # nothing to delete yet
        self.assertIn(b"\x60\x0d", cmds)                                       # load the slot Furby used (13),
        self.assertNotIn(b"\x60\x01", cmds)                                    # not the --slot argument
        self.assertTrue(bleak.SLOTS[13]["active"])
        self.assertIn(("disconnect", b""), bleak.LOG)

    def test_reupload_frees_the_old_copy_first(self):
        self.upload(os.urandom(2000))
        cmds = self.upload(os.urandom(2500))
        order = [c[:2] for c in cmds if c[:1] in (b"\x62", b"\x74", b"\x50", b"\x60", b"\x61")]
        self.assertEqual(order[:3], [b"\x62\x0d", b"\x74\x0d", b"\x50\x00"])  # deactivate, delete, upload
        self.assertEqual(bleak.SLOTS[13]["size"], 2500)

    def test_new_name_keeps_both_packs(self):
        self.upload(os.urandom(2000))
        cmds = self.upload(os.urandom(2100), "--name", "TU900010.DLC")
        self.assertNotIn(b"\x74\x0d", cmds)                                    # the other pack stays
        self.assertEqual(sorted(bleak.SLOTS), [12, 13])
        self.assertTrue(bleak.SLOTS[12]["active"])

    def test_say_chain_and_stdin(self):
        m = self.dir / "pack.json"
        m.write_text(json.dumps({"1": {"text": "Hei!", "action": [75, 0, 0, 0], "seconds": 0.05},
                                 "2": {"text": "Hyvää yötä", "action": [75, 0, 4, 7], "seconds": 0.05}}))
        run(["say", "1", "yötä", "--map", str(m), "--address", "X", "--gap", "0"])
        self.assertEqual(self.gp(), [bytes([0x13, 0, 75, 0, 0, 0]), bytes([0x13, 0, 75, 0, 4, 7])])
        self.assertEqual(sum(1 for c, _ in bleak.LOG if c == "disconnect"), 1)  # one connection
        bleak.LOG.clear()
        run(["say", "-", "--map", str(m), "--address", "X", "--gap", "0"], stdin="2\n1 | hei | nope\n")
        self.assertEqual(self.gp(), [bytes([0x13, 0, 75, 0, 4, 7])] + [bytes([0x13, 0, 75, 0, 0, 0])] * 2)


if __name__ == "__main__":
    unittest.main()
