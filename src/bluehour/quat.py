"""Quaternion and vector helpers shared by the trackers and the renderer.
"""
import math

import numpy as np

# --------------------------------------------------------------------------------------
# Quaternion / vector helpers   (quaternion = [w, x, y, z]; view space: x right, y up, -z forward)
# --------------------------------------------------------------------------------------

def q_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ])


def q_axis(axis, angle):
    s = math.sin(angle / 2.0)
    return np.array([math.cos(angle / 2.0), axis[0] * s, axis[1] * s, axis[2] * s])


def q_norm(q):
    return q / np.linalg.norm(q)


def q_rot(q, v):
    u = q[1:]
    return v + 2.0 * np.cross(u, np.cross(u, v) + q[0] * v)


def q_mat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float32)


def q_yaw(q):
    """Heading (rotation about +Y) of the forward vector."""
    f = q_rot(q, np.array([0.0, 0.0, -1.0]))
    return math.atan2(-f[0], -f[2])


IDENTITY = np.array([1.0, 0.0, 0.0, 0.0])
UP = np.array([0.0, 1.0, 0.0])
# Eye position relative to the neck pivot (metres; +y up, -z forward). Used by the neck model.
NECK = np.array([0.0, 0.075, -0.080])
