"""ESPHome generator: structure and protocol bytes. CI also runs `esphome config` and `esphome compile`."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import esphome_gen  # noqa: E402

MAP = json.loads((Path(__file__).parent / "data" / "sample_pack.json").read_text(encoding="utf-8"))


class ESPHome(unittest.TestCase):
    def setUp(self):
        self.y = esphome_gen.generate(MAP, "a1:b2:c3:d4:e5:f6")

    def test_one_button_per_item(self):
        self.assertEqual(len(re.findall(r'name: "Say \d+:', self.y)), 3)
        self.assertIn('name: "Say 2: Hyvää yötä \\"pikku\\" ystävä"', self.y)   # quotes escaped

    def test_action_table_and_bytes(self):
        self.assertIn("{75, 0, 0, 0}, {75, 0, 0, 1}, {75, 0, 4, 7}", self.y)
        self.assertIn("0x13, 0x00, (uint8_t) a", self.y)                     # play action
        self.assertIn("0x14, (uint8_t) r", self.y)                           # antenna
        self.assertIn("value: [0x00]", self.y)                               # keepalive
        self.assertIn("mac_address: A1:B2:C3:D4:E5:F6", self.y)
        self.assertIn(esphome_gen.GP_WRITE, self.y)
        self.assertIn(esphome_gen.GP_NOTIFY, self.y)

    def test_yaml_parses(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")

        class L(yaml.SafeLoader):
            pass
        L.add_multi_constructor("!", lambda loader, suffix, node: None)
        doc = yaml.load(self.y, Loader=L)
        self.assertEqual(doc["ble_client"][0]["id"], "furby")
        self.assertEqual(len(doc["api"]["actions"]), 4)
        self.assertEqual(len(doc["button"]), 2 + 3)

    def test_validation(self):
        with self.assertRaises(ValueError):
            esphome_gen.generate(MAP, "nope")
        with self.assertRaises(ValueError):
            esphome_gen.generate(MAP, "a1:b2:c3:d4:e5:f6", name="Bad Name")
        with self.assertRaises(ValueError):
            esphome_gen.generate({"1": {"text": "x", "action": [75, 0, 0, 300]}}, "a1:b2:c3:d4:e5:f6")


if __name__ == "__main__":
    unittest.main()
