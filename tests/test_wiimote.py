import unittest

from bluehour import wiimote as wm


class FakeDevice:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))

    def read(self, n, timeout=0):
        import time
        time.sleep(0.005)
        return []

    def close(self):
        pass


class ParseTests(unittest.TestCase):
    def test_buttons(self):
        self.assertEqual(wm.parse_buttons(0x00, 0x00), set())
        self.assertEqual(wm.parse_buttons(0x01 | 0x10, 0x08 | 0x80), {"left", "plus", "a", "home"})

    def test_ir_extended_decodes_and_skips_empty(self):
        # x=0x2AB, y=0x155 -> low bytes AB/55, high bits in byte 2: y hi (1)<<6, x hi (2)<<4, size 5
        block = bytes([0xAB, 0x55, (1 << 6) | (2 << 4) | 5]) + b"\xff\xff\xff" * 3
        self.assertEqual(wm.parse_ir_extended(block), [(0x2AB, 0x155, 5)])


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.dev = FakeDevice()
        self.w = wm.Wiimote(dev=self.dev, led=2, ir=True)

    def tearDown(self):
        self.w.close()

    def test_setup_sends_led_and_ir_init(self):
        ids = [w[0] for w in self.dev.writes]
        self.assertEqual(ids[0], 0x11)
        self.assertIn(0x13, ids)
        self.assertIn(0x16, ids)
        self.assertEqual(self.dev.writes[0][1], 0x20)  # LED 2

    def test_button_events_and_dpad_repeat(self):
        self.w._update_buttons({"a"}, 0.0)
        self.w._update_buttons({"a", "left"}, 1.0)
        self.assertEqual(self.w.pop_events(), ["a", "left"])
        self.w._update_buttons({"a", "left"}, 1.2)
        self.assertEqual(self.w.pop_events(), [])            # before the repeat delay
        self.w._update_buttons({"a", "left"}, 1.5)
        self.assertEqual(self.w.pop_events(), ["left"])      # repeat; "a" never repeats

    def test_ir_report_is_stored(self):
        block = bytes([10, 20, 0x03]) + b"\xff\xff\xff" * 3
        self.w._handle(bytes([0x33, 0, 0, 0, 0, 0]) + block)
        pts, _ = self.w.ir_snapshot()
        self.assertEqual(pts, [(10, 20, 3)])


if __name__ == "__main__":
    unittest.main()
