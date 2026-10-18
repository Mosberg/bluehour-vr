import math
import unittest

import numpy as np

from bluehour.quat import IDENTITY, q_axis, q_mat, q_mul, q_norm, q_rot, q_yaw


class QuatTests(unittest.TestCase):
    def test_identity_rotation_is_noop(self):
        v = np.array([0.3, -0.2, 0.9])
        np.testing.assert_allclose(q_rot(IDENTITY, v), v)

    def test_quarter_turn_about_y(self):
        q = q_axis([0, 1, 0], math.pi / 2)
        np.testing.assert_allclose(q_rot(q, np.array([0.0, 0.0, -1.0])), [-1.0, 0.0, 0.0], atol=1e-12)

    def test_multiplication_composes_rotations(self):
        a, b = q_axis([0, 1, 0], 0.4), q_axis([1, 0, 0], -0.3)
        v = np.array([0.2, 0.5, -1.0])
        np.testing.assert_allclose(q_rot(q_mul(a, b), v), q_rot(a, q_rot(b, v)), atol=1e-12)

    def test_matrix_matches_rotation(self):
        q = q_norm(np.array([0.9, 0.1, -0.3, 0.2]))
        v = np.array([0.4, -0.7, 0.2])
        np.testing.assert_allclose(q_mat(q) @ v, q_rot(q, v), atol=1e-6)

    def test_yaw_of_known_heading(self):
        self.assertAlmostEqual(q_yaw(IDENTITY), 0.0)
        self.assertAlmostEqual(q_yaw(q_axis([0, 1, 0], 0.5)), 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
