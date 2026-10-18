import unittest

import numpy as np

from bluehour.tracking import OneEuro, parse_axis_map, unpack21


def pack21(x, y, z):
    """Inverse of unpack21 (used only to build test data)."""
    x, y, z = (v & 0x1FFFFF for v in (x, y, z))
    bits = (x << 43) | (y << 22) | (z << 1)
    return bytes((bits >> (8 * (7 - i))) & 0xFF for i in range(8))


class UnpackTests(unittest.TestCase):
    def test_roundtrip_including_negatives(self):
        for triple in [(0, 0, 0), (1, -1, 2), (123456, -98765, 1000000), (-1048576, 1048575, -5)]:
            np.testing.assert_array_equal(unpack21(pack21(*triple)), triple)


class AxisMapTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_axis_map("x,y,z"), [(1.0, 0), (1.0, 1), (1.0, 2)])
        self.assertEqual(parse_axis_map("-x, z ,-y"), [(-1.0, 0), (1.0, 2), (-1.0, 1)])

    def test_rejects_wrong_length_and_names(self):
        with self.assertRaises(ValueError):
            parse_axis_map("x,y")
        with self.assertRaises(ValueError):
            parse_axis_map("x,y,w")


class OneEuroTests(unittest.TestCase):
    def test_first_sample_passes_through(self):
        f = OneEuro()
        np.testing.assert_allclose(f([1.0, 2.0, 3.0], 0.0), [1, 2, 3])

    def test_converges_to_constant_input(self):
        f = OneEuro()
        out = None
        for i in range(300):
            out = f([0.5, 0.0, -0.5], i / 75.0)
        np.testing.assert_allclose(out, [0.5, 0.0, -0.5], atol=1e-3)

    def test_smooths_jitter_when_still(self):
        rng = np.random.default_rng(1)
        f = OneEuro(mincutoff=1.0, beta=0.0)
        raw = rng.normal(0, 0.01, 400)
        smooth = [float(f([r], i / 75.0)[0]) for i, r in enumerate(raw)]
        self.assertLess(np.std(smooth[100:]), np.std(raw[100:]) * 0.6)


if __name__ == "__main__":
    unittest.main()
