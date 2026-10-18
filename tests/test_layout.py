import unittest

from bluehour.player import guess_layout


class GuessLayoutTests(unittest.TestCase):
    def test_flat_mono(self):
        self.assertEqual(guess_layout("holiday.mp4"), (0, 0))

    def test_vr180_sbs(self):
        self.assertEqual(guess_layout("/media/clip_180_sbs.mp4"), (2, 1))

    def test_vr360_over_under(self):
        self.assertEqual(guess_layout("sky_360_ou.mkv"), (3, 2))

    def test_directory_names_are_ignored(self):
        self.assertEqual(guess_layout("/videos/360_sbs/plain.mp4"), (0, 0))

    def test_stereo_hint_defaults(self):
        self.assertEqual(guess_layout("x_180_3d.mp4"), (2, 1))
        self.assertEqual(guess_layout("x_360_stereo.mp4"), (3, 2))


if __name__ == "__main__":
    unittest.main()
