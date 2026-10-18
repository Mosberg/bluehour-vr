#!/usr/bin/env python3
"""
Minimal Wii Remote driver over Bluetooth HID (via hidapi) for Bluehour.

Supports: buttons (with D-pad auto-repeat), the IR camera (up to 4 tracked points), player LEDs,
rumble and battery level. No accelerometer / extensions.

The remote must already be paired with the PC as a Bluetooth HID device (see README, section 7).

Run this file directly to test a remote:   python -m bluehour.wiimote [--ir]
"""

from __future__ import annotations

import collections
import sys
import threading
import time

VID = 0x057E
PIDS = (0x0306, 0x0330)  # RVL-CNT-01 and RVL-CNT-01-TR (Wii Remote Plus)

# name -> (index among the two button bytes, bit mask)
BUTTONS = {
    "left": (0, 0x01),
    "right": (0, 0x02),
    "down": (0, 0x04),
    "up": (0, 0x08),
    "plus": (0, 0x10),
    "two": (1, 0x01),
    "one": (1, 0x02),
    "b": (1, 0x04),
    "a": (1, 0x08),
    "minus": (1, 0x10),
    "home": (1, 0x80),
}
REPEAT = {"left", "right", "up", "down"}
REPEAT_DELAY = 0.45
REPEAT_RATE = 0.15

# IR camera sensitivity presets (WiiBrew levels 1-5): (block 1 -> 0xB00000, block 2 -> 0xB0001A)
IR_LEVELS = {
    1: (bytes.fromhex("02000071010064" "00fe"), bytes.fromhex("fd05")),
    2: (bytes.fromhex("02000071010096" "00b4"), bytes.fromhex("b304")),
    3: (bytes.fromhex("020000710100aa" "0064"), bytes.fromhex("6303")),
    4: (bytes.fromhex("020000710100c8" "0036"), bytes.fromhex("3503")),
    5: (bytes.fromhex("0700007101007200" "20"), bytes.fromhex("1f03")),
}


def parse_buttons(b0, b1):
    """Names of the buttons held, from the two button bytes of an input report."""
    raw = (b0, b1)
    return {name for name, (idx, mask) in BUTTONS.items() if raw[idx] & mask}


def parse_ir_extended(data):
    """Decode the 12-byte 'extended' IR block into a list of (x, y, size); x 0-1023, y 0-767."""
    pts = []
    for i in range(4):
        b = data[3 * i : 3 * i + 3]
        if len(b) < 3 or (b[0] == 0xFF and b[1] == 0xFF and b[2] == 0xFF):
            continue
        x = b[0] | (((b[2] >> 4) & 0x03) << 8)
        y = b[1] | (((b[2] >> 6) & 0x03) << 8)
        pts.append((x, y, b[2] & 0x0F))
    return pts


class Wiimote:
    def __init__(self, path=None, led=1, ir=False, ir_level=3, debug=False, dev=None):
        self.path = path
        self.led = led
        self.ir_enabled = ir
        self.ir_level = ir_level
        self.debug = debug
        self.dev = dev
        self.lock = threading.Lock()
        self.events = collections.deque(maxlen=64)
        self.ir = []
        self.ir_time = 0.0
        self.battery = None
        self.connected = False
        self.running = True
        self._rumble = 0
        self._prev = set()
        self._held = {}
        if self.dev is None:
            self._open()
        self._setup()
        self.connected = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # ---------------- discovery / connection ----------------
    @staticmethod
    def find():
        """Paths of all connected Wii Remotes."""
        import hid  # pip install hidapi

        seen, out = set(), []
        for pid in PIDS:
            for d in hid.enumerate(VID, pid):
                if d["path"] not in seen:
                    seen.add(d["path"])
                    out.append(d["path"])
        return out

    def _open(self):
        import hid

        dev = hid.device()
        dev.open_path(self.path)
        dev.set_nonblocking(0)
        self.dev = dev

    # ---------------- low-level output ----------------
    def _write(self, report_id, payload):
        payload = bytearray(payload)
        if payload:
            payload[
                0
            ] |= self._rumble  # bit 0 of every output report is the rumble flag
        data = bytes([report_id]) + bytes(payload)
        if sys.platform == "win32":
            data = data.ljust(
                22, b"\x00"
            )  # Windows requires full-length output reports
        self.dev.write(data)

    def _write_reg(self, address, data):
        payload = (
            bytes([0x04])
            + address.to_bytes(3, "big")
            + bytes([len(data)])
            + bytes(data).ljust(16, b"\x00")
        )
        self._write(0x16, payload)
        time.sleep(0.05)

    def _led_byte(self):
        return 0x10 << (max(1, min(4, self.led)) - 1)

    def _setup(self):
        self._write(0x11, [self._led_byte()])
        if self.ir_enabled:
            self._write(0x13, [0x04])  # IR pixel clock on
            time.sleep(0.05)
            self._write(0x1A, [0x04])  # IR logic on
            time.sleep(0.05)
            self._write_reg(0xB00030, b"\x08")
            block1, block2 = IR_LEVELS.get(self.ir_level, IR_LEVELS[3])
            self._write_reg(0xB00000, block1)
            self._write_reg(0xB0001A, block2)
            self._write_reg(0xB00033, b"\x03")  # extended IR mode (position + size)
            self._write_reg(0xB00030, b"\x08")
            self._mode = 0x33  # buttons + accel + 12 IR bytes
        else:
            self._mode = 0x30  # buttons only
        self._write(0x12, [0x04, self._mode])  # 0x04 = report continuously
        self._write(0x15, [0x00])  # ask for a status report (battery)

    # ---------------- reading ----------------
    def _run(self):
        while self.running:
            try:
                data = self.dev.read(32, 100)
            except Exception:  # noqa: BLE001
                self._lost()
                continue
            if data:
                self._handle(bytes(data))

    def _lost(self):
        self.connected = False
        if self.path is None:  # injected device (tests): stop
            self.running = False
            return
        while self.running:
            time.sleep(2.0)
            try:
                self._open()
                self._setup()
                self.connected = True
                if self.debug:
                    print("Wii Remote reconnected")
                return
            except Exception:  # noqa: BLE001
                pass

    def _handle(self, data):
        rid = data[0]
        if 0x30 <= rid <= 0x37 and len(data) >= 3:
            now = time.time()
            self._update_buttons(parse_buttons(data[1], data[2]), now)
            if rid == 0x33 and len(data) >= 18:
                pts = parse_ir_extended(data[6:18])
                with self.lock:
                    self.ir = pts
                    self.ir_time = now
        elif rid == 0x20 and len(data) >= 7:
            self.battery = min(100, data[6] * 100 // 200)
            if self.debug:
                print("Wii Remote battery ~%d%%" % self.battery)
            try:  # status reports reset the reporting mode on real hardware
                self._write(0x12, [0x04, self._mode])
            except Exception:  # noqa: BLE001
                pass

    def _update_buttons(self, names, now):
        with self.lock:
            for name in names - self._prev:
                self.events.append(name)
                self._held[name] = [now, now]
            for name in names & self._prev & REPEAT:
                t0, tlast = self._held.get(name, [now, now])
                if now - t0 > REPEAT_DELAY and now - tlast > REPEAT_RATE:
                    self.events.append(name)
                    self._held[name][1] = now
            for name in self._prev - names:
                self._held.pop(name, None)
            self._prev = set(names)

    # ---------------- public API ----------------
    def pop_events(self):
        """Button presses (and D-pad repeats) since the last call, as names like 'a', 'left'."""
        with self.lock:
            out = list(self.events)
            self.events.clear()
        return out

    def ir_snapshot(self):
        with self.lock:
            return list(self.ir), self.ir_time

    def rumble(self, seconds=0.12):
        self._rumble = 1
        try:
            self._write(0x11, [self._led_byte()])
        except Exception:  # noqa: BLE001
            return
        threading.Timer(seconds, self._rumble_off).start()

    def _rumble_off(self):
        self._rumble = 0
        try:
            self._write(0x11, [self._led_byte()])
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        self.running = False
        try:
            if self.ir_enabled:
                self._write(0x13, [0x00])
                self._write(0x1A, [0x00])
            self._write(0x12, [0x00, 0x30])
            self._write(0x11, [0x00])
            self.thread.join(timeout=0.5)
            self.dev.close()
        except Exception:  # noqa: BLE001
            pass


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Wii Remote test")
    ap.add_argument("--ir", action="store_true", help="also show IR camera points")
    ap.add_argument("--ir-level", type=int, default=3, choices=range(1, 6))
    args = ap.parse_args()
    paths = Wiimote.find()
    if not paths:
        raise SystemExit("No Wii Remote found. Pair it first (see README section 7).")
    wm = Wiimote(paths[0], led=1, ir=args.ir, ir_level=args.ir_level, debug=True)
    print("Connected. Press buttons; Ctrl+C quits.")
    last = 0.0
    try:
        while True:
            for ev in wm.pop_events():
                print("button:", ev)
                if ev == "b":
                    wm.rumble()
            if args.ir and time.time() - last > 0.5:
                pts, _ = wm.ir_snapshot()
                print("IR points:", pts if pts else "none")
                last = time.time()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        wm.close()


if __name__ == "__main__":
    main()
