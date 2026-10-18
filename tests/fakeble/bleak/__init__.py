"""Fake bleak for tests: simulates a Furby Connect (see tests/test_ble.py).

Behaves like the real toy did on 2026-10-18: the announced file name picks the slot (same name ->
same slot, a new name -> the next free slot counting down from 13), 73/74/60/61/62 answer with
73/74/dc packets.
"""
import asyncio
LOG = []          # (char, bytes)
FILE = bytearray()
SLOTS = {}        # slot -> {"name": bytes(8), "size": int, "active": bool}
class BleakScanner:
    @staticmethod
    async def discover(timeout=10.0):
        from bleak.backends.device import BLEDevice
        return [BLEDevice("AA:BB:CC:DD:EE:FF", "Furby")]
class BleakClient:
    def __init__(self, dev, timeout=10.0):
        self.dev, self._conn, self.notify = dev, False, {}
        self.expect = None
        self.loaded = None
    @property
    def is_connected(self): return self._conn
    async def connect(self): self._conn = True
    async def disconnect(self): self._conn = False; LOG.append(("disconnect", b""))
    async def start_notify(self, char, cb): self.notify[str(char).lower()] = cb
    def _gp(self, data):
        for k, cb in self.notify.items():
            if k.startswith("dab91382"):
                asyncio.get_running_loop().call_soon(cb, 0, bytes(data))
    def _slot_for(self, name):
        for s, v in SLOTS.items():
            if v["name"] == name:
                return s
        return next(s for s in range(13, -1, -1) if s not in SLOTS)
    async def write_gatt_char(self, char, data, response=True):
        c = str(char).lower(); data = bytes(data)
        if c.startswith("dab90758"):
            FILE.extend(data)
            if self.expect and len(FILE) >= self.expect[1]:
                name, size = self.expect
                SLOTS[self._slot_for(name)] = {"name": name, "size": size, "active": False}
                self.expect = None; self._gp(b"\x24\x05")
            return
        LOG.append((c[:8], data))
        if not c.startswith("dab91383") or not data:
            return
        op = data[0]
        if op == 0x50:
            self.expect = (data[6:14], int.from_bytes(data[2:5], "big")); FILE.clear(); self._gp(b"\x24\x02")
        elif op == 0x73:
            v = SLOTS.get(data[1])
            body = v["name"] + v["size"].to_bytes(3, "big") + b"\x00\x00\x00\x00" if v else bytes(15)
            self._gp(bytes([0x73, data[1]]) + body)
        elif op == 0x74:
            SLOTS.pop(data[1], None); self._gp(bytes([0x74, data[1], 1]))
        elif op == 0x60:
            self.loaded = data[1]; self._gp(bytes([0xdc, data[1], 1]))
        elif op == 0x61 and self.loaded in SLOTS:
            for v in SLOTS.values():
                v["active"] = False
            SLOTS[self.loaded]["active"] = True; self._gp(bytes([0xdc, self.loaded, 2]))
        elif op == 0x62 and data[1] in SLOTS:
            SLOTS[data[1]]["active"] = False; self._gp(bytes([0xdc, data[1], 4]))
