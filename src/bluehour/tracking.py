"""Head and position trackers: DK2 IMU, DK2 IR camera, Wii Remote IR camera, mouse fallback.
"""
import math
import struct
import sys
import threading
import time

import numpy as np

from .quat import IDENTITY, UP, q_axis, q_mul, q_norm, q_rot, q_yaw

# --------------------------------------------------------------------------------------
# Head trackers
# --------------------------------------------------------------------------------------

class MouseTracker:
    """Mouse-look fallback (also handy for testing without the headset)."""
    name = "mouse"

    def __init__(self):
        self.yaw = 0.0
        self.pitch = 0.0

    def add(self, dx, dy, sens=0.0025):
        self.yaw -= dx * sens
        self.pitch = max(-1.55, min(1.55, self.pitch - dy * sens))

    def orientation(self):
        return q_mul(q_axis((0, 1, 0), self.yaw), q_axis((1, 0, 0), self.pitch))

    def recenter(self):
        self.yaw = 0.0

    def offset_quat(self):
        return IDENTITY

    def close(self):
        pass


def unpack21(b):
    """Decode three signed 21-bit values packed into 8 bytes (Oculus sensor sample format)."""
    x = (b[0] << 13) | (b[1] << 5) | ((b[2] & 0xF8) >> 3)
    y = ((b[2] & 0x07) << 18) | (b[3] << 10) | (b[4] << 2) | ((b[5] & 0xC0) >> 6)
    z = ((b[5] & 0x3F) << 15) | (b[6] << 7) | (b[7] >> 1)
    out = []
    for v in (x, y, z):
        if v & 0x100000:
            v -= 1 << 21
        out.append(v)
    return np.array(out, dtype=np.float64)


def parse_axis_map(text):
    """'x,y,z' / '-x,z,y' ... maps incoming sensor axes onto view-space axes."""
    out = []
    for p in text.replace(" ", "").split(","):
        sign = -1.0 if p.startswith("-") else 1.0
        out.append((sign, "xyz".index(p.lstrip("+-"))))
    if len(out) != 3:
        raise ValueError("axis map needs 3 entries")
    return out


class DK2Tracker:
    """Reads the DK2 IMU over USB HID and fuses gyro + accelerometer into an orientation."""
    name = "dk2"
    VID, PID = 0x2833, 0x0021

    def __init__(self, axis_map="x,y,z", debug=False, enable_leds=True):
        import hid  # pip install hidapi
        self.hid = hid
        self.dev = hid.device()
        self.dev.open(self.VID, self.PID)
        self.axis_map = parse_axis_map(axis_map)
        self.debug = debug
        self.q = IDENTITY.copy()
        self.offset = IDENTITY.copy()
        self.lock = threading.Lock()
        self.running = True
        self.packets = 0
        self._keepalive()
        if enable_leds:
            self._enable_leds()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _enable_leds(self):
        """Best effort: switch the headset's IR tracking LEDs on (feature report 0x0C).

        Layout recalled from the Oculus HID documentation, not verified on hardware:
        [id, command_id(2), pattern, flags, reserved, exposure_us(2), frame_interval_us(2),
         vsync_offset(2), duty_cycle]. Flags = enable | auto-increment | carrier | sync-in | vsync-lock.
        """
        flags = 0x01 | 0x02 | 0x04 | 0x08 | 0x10
        pkt = struct.pack("<BHBBBHHHB", 0x0C, 0, 0, flags, 0, 350, 16666, 0, 127)
        try:
            self.dev.send_feature_report(pkt)
        except Exception as exc:  # noqa: BLE001
            if self.debug:
                print("LED enable failed:", exc)

    def offset_quat(self):
        with self.lock:
            return self.offset.copy()

    def _keepalive(self):
        # feature report 0x11: [id, command_id(2), keepalive_ms(2)]
        try:
            self.dev.send_feature_report(bytes([0x11, 0, 0]) + struct.pack("<H", 10000))
        except Exception as exc:  # noqa: BLE001
            if self.debug:
                print("keepalive failed:", exc)

    def _remap(self, v):
        return np.array([s * v[i] for s, i in self.axis_map])

    def _integrate(self, gyro, accel, dt):
        w = np.linalg.norm(gyro)
        with self.lock:
            if w * dt > 1e-9:
                self.q = q_norm(q_mul(self.q, q_axis(gyro / w, w * dt)))
            an = np.linalg.norm(accel)
            if 8.0 < an < 11.6:  # roughly 1 g -> trust it for tilt correction
                aw = q_rot(self.q, accel / an)
                err = np.cross(aw, UP)
                ang = np.linalg.norm(err)
                if ang > 1e-6:
                    corr = q_axis(err / ang, ang * min(1.0, 2.0 * dt))
                    self.q = q_norm(q_mul(corr, self.q))

    def _run(self):
        last_ts = None
        last_ka = time.time()
        while self.running:
            now = time.time()
            if now - last_ka > 3.0:
                self._keepalive()
                last_ka = now
            try:
                data = self.dev.read(64, 200)
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
                continue
            if not data or len(data) < 44 or data[0] != 0x0B:
                continue
            raw = bytes(data)
            num = raw[3]
            ts = struct.unpack_from("<I", raw, 8)[0]
            n = min(num, 2)
            if n == 0:
                continue
            if last_ts is None:
                dt_total = 0.001 * num
            else:
                dt_total = ((ts - last_ts) & 0xFFFFFFFF) / 1e6
            last_ts = ts
            dt = min(0.01, max(0.0002, dt_total / max(num, 1)))
            for i in range(n):
                off = 12 + 16 * i
                accel = self._remap(unpack21(raw[off:off + 8]) * 1e-4)
                gyro = self._remap(unpack21(raw[off + 8:off + 16]) * 1e-4)
                self._integrate(gyro, accel, dt)
            self.packets += 1
            if self.debug and self.packets % 75 == 0:
                print("dk2 packets=%d  yaw=%.1f deg" % (self.packets, math.degrees(q_yaw(self.q))))

    def orientation(self):
        with self.lock:
            return q_mul(self.offset, self.q)

    def recenter(self):
        with self.lock:
            self.offset = q_axis((0, 1, 0), -q_yaw(self.q))

    def close(self):
        self.running = False
        try:
            self.thread.join(timeout=0.5)
            self.dev.close()
        except Exception:  # noqa: BLE001
            pass


class OneEuro:
    """Adaptive low-pass filter (smooth when still, responsive when moving)."""

    def __init__(self, mincutoff=1.0, beta=8.0, dcutoff=1.0):
        self.mincutoff, self.beta, self.dcutoff = mincutoff, beta, dcutoff
        self.reset()

    def reset(self):
        self.t = None
        self.x = None
        self.dx = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        x = np.asarray(x, dtype=np.float64)
        if self.t is None:
            self.t, self.x, self.dx = t, x.copy(), np.zeros_like(x)
            return self.x
        dt = max(1e-3, t - self.t)
        self.dx = self._alpha(self.dcutoff, dt) * ((x - self.x) / dt) + \
            (1.0 - self._alpha(self.dcutoff, dt)) * self.dx
        a = self._alpha(self.mincutoff + self.beta * float(np.linalg.norm(self.dx)), dt)
        self.x = a * x + (1.0 - a) * self.x
        self.t = t
        return self.x


class CameraTracker:
    """EXPERIMENTAL positional tracking from the DK2 IR camera.

    The headset's IR LEDs show up as bright dots. We do not identify individual LEDs (that needs the
    blink-pattern decoding of the official runtime); instead we track the dot cluster as a whole:
      * left/right and up/down  <- cluster centroid in the image
      * forward/back            <- cluster height in the image (vertical spread, which stays roughly
                                   constant when you turn your head, unlike the horizontal spread)
    It is a crude 3-axis position estimate (no roll/pitch/yaw from the camera; those come from the IMU).
    Position is reported in metres relative to the pose at the last recenter, in view-space axes
    (x right, y up, z back toward the user; moving toward the screen/camera gives negative z).
    """
    name = "camera"
    SIZE = (752, 480)

    def __init__(self, index=None, hfov=74.0, distance=1.0, threshold=180, min_blobs=4,
                 axis_map="x,y,z", debug=False, autostart=True):
        import cv2  # pip install opencv-python
        self.cv2 = cv2
        self.debug = debug
        self.threshold = threshold
        self.min_blobs = min_blobs
        self.distance = distance
        self.axis_map = parse_axis_map(axis_map)
        self.cap, self.index = self._open(index)
        ok, frame = self.cap.read()
        if not ok or frame is None:
            raise RuntimeError("camera %s gives no frames" % self.index)
        self.h, self.w = frame.shape[:2]
        self.f = (self.w / 2.0) / math.tan(math.radians(hfov) / 2.0)
        self.lock = threading.Lock()
        self.f_xy = OneEuro(mincutoff=1.5, beta=10.0)
        self.f_z = OneEuro(mincutoff=0.5, beta=4.0)
        self.pos = np.zeros(3)
        self.ref = None          # (X0, Y0) in metres at the reference pose
        self.ref_sy = None
        self.need_ref = True
        self.last_ok = 0.0
        self.frames = 0
        self.running = True
        self.thread = None
        if autostart:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _open(self, index):
        cv2 = self.cv2
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        for i in ([index] if index is not None else range(8)):
            cap = cv2.VideoCapture(i, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.SIZE[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.SIZE[1])
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                if index is not None or (w, h) == self.SIZE:
                    return cap, i
            cap.release()
        raise RuntimeError("DK2 camera not found (it should appear as a 752x480 camera; "
                           "see --list-cameras and --camera N)")

    # -- image processing -------------------------------------------------------------
    def detect(self, frame):
        """Return ((cx, cy, spread_y), blobs) for one frame, or (None, blobs)."""
        cv2 = self.cv2
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, bw = cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY)
        n, _, stats, cents = cv2.connectedComponentsWithStats(bw, connectivity=8)
        pts = [cents[i] for i in range(1, n) if 2 <= stats[i, cv2.CC_STAT_AREA] <= 600]
        if len(pts) < self.min_blobs or len(pts) > 120:
            return None, np.array(pts).reshape(-1, 2)
        pts = np.array(pts)
        med = np.median(pts, axis=0)
        d = np.linalg.norm(pts - med, axis=1)
        pts = pts[d <= max(40.0, 2.5 * float(np.median(d)))]  # drop stray reflections
        if len(pts) < self.min_blobs:
            return None, pts
        c = pts.mean(axis=0)
        sy = float(np.sqrt(np.mean((pts[:, 1] - c[1]) ** 2)))
        if sy < 1.5:
            return None, pts
        return (float(c[0]), float(c[1]), sy), pts

    def _xyz(self, cx, cy, sy):
        """Metric position (camera frame, before referencing) from a measurement."""
        z = self.distance * self.ref_sy / sy
        x = -((cx - self.w / 2.0) / self.f) * z   # user's right = image left (camera faces the user)
        y = -((cy - self.h / 2.0) / self.f) * z
        return x, y, z

    def step(self, frame):
        """Process one frame; returns (position_or_None, blobs)."""
        meas, pts = self.detect(frame)
        self.frames += 1
        if meas is None:
            return None, pts
        cx, cy, sy = meas
        now = time.time()
        with self.lock:
            if self.need_ref or self.ref_sy is None:
                self.ref_sy = sy
                x0, y0, _ = self._xyz(cx, cy, sy)
                self.ref = (x0, y0)
                self.need_ref = False
                self.f_xy.reset()
                self.f_z.reset()
            x, y, z = self._xyz(cx, cy, sy)
            xy = self.f_xy(np.array([x - self.ref[0], y - self.ref[1]]), now)
            zz = self.f_z(np.array([z - self.distance]), now)
            raw = np.array([xy[0], xy[1], zz[0]])
            self.pos = np.array([s * raw[i] for s, i in self.axis_map])
            self.last_ok = now
            return self.pos.copy(), pts

    def _run(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            self.step(frame)
            if self.debug and self.frames % 120 == 0:
                print("camera frames=%d healthy=%s pos=%s" % (self.frames, self.healthy(), np.round(self.pos, 3)))

    # -- public API -------------------------------------------------------------------
    def healthy(self):
        return (time.time() - self.last_ok) < 0.4

    def position(self):
        with self.lock:
            return self.pos.copy()

    def recenter(self):
        with self.lock:
            self.need_ref = True

    def close(self):
        self.running = False
        try:
            if self.thread is not None:
                self.thread.join(timeout=0.5)
            self.cap.release()
        except Exception:  # noqa: BLE001
            pass


def list_cameras():
    import cv2
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    found = False
    for i in range(10):
        cap = cv2.VideoCapture(i, backend)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                tag = "   <- looks like the DK2 camera" if (w, h) == CameraTracker.SIZE else ""
                print("camera %d: %dx%d%s" % (i, w, h, tag))
                found = True
        cap.release()
    if not found:
        print("no cameras found")


def camera_test(args):
    """Stand-alone preview of the camera tracker (no OpenGL / mpv needed)."""
    import cv2
    cam = CameraTracker(args.camera, args.cam_fov, args.cam_distance, args.cam_threshold,
                        axis_map=args.cam_axis_map, debug=args.debug, autostart=False)
    print("Camera test on camera %d (%dx%d). Keys: R = recenter, Q/Esc = quit." % (cam.index, cam.w, cam.h))
    last_print = 0.0
    while True:
        ok, frame = cam.cap.read()
        if not ok or frame is None:
            continue
        pos, pts = cam.step(frame)
        view = frame if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        for p in pts:
            cv2.circle(view, (int(p[0]), int(p[1])), 6, (0, 255, 0), 1)
        label = "no LEDs found" if pos is None else "x %+.3f  y %+.3f  z %+.3f m" % tuple(pos)
        cv2.putText(view, label, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow("DK2 camera test", view)
        if time.time() - last_print > 0.5:
            print(label + "   blobs=%d" % len(pts))
            last_print = time.time()
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        if key == ord("r"):
            cam.recenter()
    cam.close()
    cv2.destroyAllWindows()


class WiiPosition:
    """EXPERIMENTAL position from a Wii Remote IR camera that watches the DK2's LEDs.

    The remote reports up to its four brightest IR points (1024x768). We use their centroid for
    left/right + up/down and their vertical spread for forward/back, like CameraTracker. Because only
    the four brightest points are reported and the DK2's ~40 LEDs merge into a few blobs, this is
    noisier than the DK2 camera. Same output convention as CameraTracker.
    """
    name = "wii"
    W, H = 1024, 768

    def __init__(self, wii, hfov=45.0, distance=1.0, axis_map="x,y,z"):
        self.wii = wii
        self.distance = distance
        self.axis_map = parse_axis_map(axis_map)
        self.f = (self.W / 2.0) / math.tan(math.radians(hfov) / 2.0)
        self.f_xy = OneEuro(mincutoff=1.5, beta=10.0)
        self.f_z = OneEuro(mincutoff=0.5, beta=4.0)
        self.pos = np.zeros(3)
        self.ref = None
        self.ref_sy = None
        self.need_ref = True
        self.last_ok = 0.0
        self.last_t = 0.0
        self.last_z = distance

    def _xy(self, cx, cy, z):
        return -((cx - self.W / 2.0) / self.f) * z, -((cy - self.H / 2.0) / self.f) * z

    def _poll(self):
        pts, t = self.wii.ir_snapshot()
        if t == self.last_t:
            return
        self.last_t = t
        if not pts:
            return
        xs = np.array([p[0] for p in pts], dtype=np.float64)
        ys = np.array([p[1] for p in pts], dtype=np.float64)
        cx, cy = float(xs.mean()), float(ys.mean())
        sy = float(np.sqrt(np.mean((ys - cy) ** 2))) if len(pts) >= 2 else 0.0
        have_sy = sy >= 1.5
        if self.need_ref:
            self.ref_sy = sy if have_sy else None
            self.last_z = self.distance
            self.ref = self._xy(cx, cy, self.distance)
            self.need_ref = False
            self.f_xy.reset()
            self.f_z.reset()
        if self.ref_sy is None and have_sy:
            self.ref_sy = sy                    # first usable spread becomes the distance reference
        z = self.distance * self.ref_sy / sy if (have_sy and self.ref_sy) else self.last_z
        self.last_z = z
        x, y = self._xy(cx, cy, z)
        now = time.time()
        xy = self.f_xy(np.array([x - self.ref[0], y - self.ref[1]]), now)
        zz = self.f_z(np.array([z - self.distance]), now)
        raw = np.array([xy[0], xy[1], zz[0]])
        self.pos = np.array([s * raw[i] for s, i in self.axis_map])
        self.last_ok = now

    def healthy(self):
        self._poll()
        return (time.time() - self.last_ok) < 0.4

    def position(self):
        self._poll()
        return self.pos.copy()

    def recenter(self):
        self.need_ref = True

    def close(self):
        pass


def setup_wiimotes(args):
    """Open Wii Remotes according to --wii. Returns (controller, camera_remote); either may be None."""
    mode = args.wii
    if mode == "off":
        return None, None
    try:
        from .wiimote import Wiimote
        paths = Wiimote.find()
    except Exception as exc:  # noqa: BLE001
        if mode != "auto":
            print("Wii Remote support unavailable (%s)" % exc)
        return None, None
    if args.wii_swap:
        paths = paths[::-1]
    if not paths:
        if mode != "auto":
            print("No paired Wii Remote found (see README section 7).")
        return None, None
    ctl_path = cam_path = None
    if mode == "controller" or (mode == "auto" and len(paths) == 1):
        ctl_path = paths[0]
    elif mode == "camera":
        cam_path = paths[0]
    else:  # both, or auto with two or more remotes
        ctl_path = paths[0]
        cam_path = paths[1] if len(paths) > 1 else None
        if cam_path is None:
            print("Only one Wii Remote found: using it as the controller (the camera role needs a second one).")
    ctl = cam = None
    try:
        if ctl_path is not None:
            ctl = Wiimote(ctl_path, led=1, ir=False, debug=args.debug)
            print("Wii Remote controller connected (LED 1)")
        if cam_path is not None:
            cam = Wiimote(cam_path, led=4, ir=True, ir_level=args.wii_ir_level, debug=args.debug)
            print("Wii Remote IR camera connected (LED 4): stand it on the monitor facing you, A button up")
    except Exception as exc:  # noqa: BLE001
        print("Wii Remote failed to start: %s" % exc)
    return ctl, cam


def wii_test(args):
    """Stand-alone Wii Remote check: shows buttons, IR points and the computed position."""
    ctl, cam = setup_wiimotes(args)
    if ctl is None and cam is None:
        raise SystemExit("No Wii Remote could be opened. See README section 7 (pairing).")
    pos = WiiPosition(cam, args.wii_fov, args.wii_distance, args.wii_axis_map) if cam else None
    print("Wii test. Controller buttons are printed; press A on the controller to recenter the position. "
          "Ctrl+C quits.")
    last = 0.0
    try:
        while True:
            if ctl is not None:
                for ev in ctl.pop_events():
                    print("button:", ev)
                    if ev == "a" and pos is not None:
                        pos.recenter()
                        print("recentered")
            if pos is not None and time.time() - last > 0.5:
                pts, _ = cam.ir_snapshot()
                p = pos.position()
                print("IR points: %s   position x %+.3f y %+.3f z %+.3f m   %s" % (
                    pts if pts else "none", p[0], p[1], p[2], "" if pos.healthy() else "(no recent IR data)"))
                last = time.time()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        for r in (ctl, cam):
            if r is not None:
                r.close()


def make_tracker(kind, axis_map, debug, enable_leds=True):
    if kind in ("auto", "dk2"):
        try:
            tracker = DK2Tracker(axis_map, debug, enable_leds)
            print("Head tracking: DK2 IMU (rotation)")
            return tracker
        except Exception as exc:  # noqa: BLE001
            print("DK2 tracker unavailable (%s) -> using mouse look" % exc)
    return MouseTracker()
