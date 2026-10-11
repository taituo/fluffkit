"""Fake bleak for tests: simulates a Furby Connect (see tests/test_ble.py)."""
import asyncio
LOG = []          # (char, bytes)
FILE = bytearray()
class BleakScanner:
    @staticmethod
    async def discover(timeout=10.0):
        from bleak.backends.device import BLEDevice
        return [BLEDevice("AA:BB:CC:DD:EE:FF", "Furby")]
class BleakClient:
    def __init__(self, dev, timeout=10.0):
        self.dev, self._conn, self.notify = dev, False, {}
        self.expect = None
    @property
    def is_connected(self): return self._conn
    async def connect(self): self._conn = True
    async def disconnect(self): self._conn = False; LOG.append(("disconnect", b""))
    async def start_notify(self, char, cb): self.notify[str(char).lower()] = cb
    def _gp(self, data):
        for k, cb in self.notify.items():
            if k.startswith("dab91382"):
                asyncio.get_running_loop().call_soon(cb, 0, bytes(data))
    async def write_gatt_char(self, char, data, response=True):
        c = str(char).lower(); data = bytes(data)
        if c.startswith("dab90758"):
            FILE.extend(data)
            if self.expect and len(FILE) >= self.expect:
                self.expect = None; self._gp(b"\x24\x05")
            return
        LOG.append((c[:8], data))
        if c.startswith("dab91383") and data[:1] == b"\x50":
            self.expect = int.from_bytes(data[2:5], "big"); FILE.clear(); self._gp(b"\x24\x02")
