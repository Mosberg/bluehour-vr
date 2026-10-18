"""The player: window, mpv, rendering loop, input handling and command line."""

from __future__ import annotations

import argparse
import os
import queue
import signal
import sys
import threading
import time

import numpy as np

from . import __version__, control, settings
from .paths import prepare_library_path
from .gui import Overlay
from .quat import NECK, q_mat, q_rot
from .shaders import EYE_FRAG, PRESENT_FRAG, VERT
from .tracking import (
    CameraTracker,
    MouseTracker,
    WiiPosition,
    camera_test,
    list_cameras,
    make_tracker,
    setup_wiimotes,
    wii_test,
)

# --------------------------------------------------------------------------------------
# Player
# --------------------------------------------------------------------------------------

PROJ_NAMES = list(settings.PROJ)
STEREO_NAMES = list(settings.STEREO)
POS_NAMES = list(settings.POSITION)
ROTATE_NAMES = list(settings.ROTATE)


def guess_layout(path):
    """Guess projection/stereo from the file name (e.g. movie_180_sbs.mp4)."""
    n = os.path.basename(str(path)).lower()
    proj = 0
    if "360" in n:
        proj = 3
    elif "180" in n:
        proj = 2
    stereo = 0
    if any(t in n for t in ("sbs", "_lr", "lr_", "side-by-side", "sidebyside", "-lr")):
        stereo = 1
    elif any(
        t in n
        for t in (
            "_ou",
            "_tb",
            "over-under",
            "overunder",
            "top-bottom",
            "topbottom",
            "-tb",
        )
    ):
        stereo = 2
    if proj in (2, 3) and stereo == 0 and any(t in n for t in ("stereo", "3d")):
        stereo = 2 if proj == 3 else 1
    return proj, stereo


class App:
    def __init__(self, args, files):
        self.args = args
        self.files = files
        self.proj, self.stereo = guess_layout(files[0])
        if args.proj:
            self.proj = PROJ_NAMES.index(args.proj)
        if args.stereo:
            self.stereo = STEREO_NAMES.index(args.stereo)
        self.swap = 1 if args.swap_eyes else 0
        self.screen_w = args.screen_width
        self.dist = args.distance
        self.ipd = args.ipd / 1000.0
        self.tan_half = args.fov_scale
        self.ca = args.ca
        self.k = list(args.k)
        self.rotate = ROTATE_NAMES.index(args.rotate)
        self.vw, self.vh = 1920, 1080
        self.vfbo = self.vtex = None
        self.ofbo = self.otex = None
        self.osize = (0, 0)
        self.last_cursor = None
        self.tracker = make_tracker(
            args.tracking, args.axis_map, args.debug, not args.no_led_enable
        )
        self.overlay = Overlay(self)
        self.pos_mode = POS_NAMES.index(args.position)
        self.pos_scale = args.move_scale
        self.pos_src = "none"
        self.camera = None
        if args.position in ("auto", "camera"):
            try:
                self.camera = CameraTracker(
                    args.camera,
                    args.cam_fov,
                    args.cam_distance,
                    args.cam_threshold,
                    axis_map=args.cam_axis_map,
                    debug=args.debug,
                )
                print(
                    "Position tracking: DK2 camera %d (experimental) + neck model fallback"
                    % self.camera.index
                )
            except Exception as exc:  # noqa: BLE001
                print("Camera tracking unavailable (%s) -> neck model only" % exc)
        self.wii_ctl, self.wii_cam = setup_wiimotes(args)
        self.wii_pos = (
            WiiPosition(
                self.wii_cam, args.wii_fov, args.wii_distance, args.wii_axis_map
            )
            if self.wii_cam is not None
            else None
        )
        self.wii_keys = {  # Wii Remote button -> the keyboard key it triggers
            "a": glfw.KEY_SPACE,
            "b": glfw.KEY_R,
            "left": glfw.KEY_LEFT,
            "right": glfw.KEY_RIGHT,
            "up": glfw.KEY_UP,
            "down": glfw.KEY_DOWN,
            "plus": glfw.KEY_PAGE_UP,
            "minus": glfw.KEY_PAGE_DOWN,
            "one": glfw.KEY_S,
            "home": glfw.KEY_V,
        }
        self.pad = None
        if not args.no_gamepad:
            try:
                from . import gamepad

                self.pad = gamepad.GamepadInput(
                    gamepad.GlfwBackend(glfw), args.pad_file or gamepad.default_path()
                )
            except Exception as exc:  # noqa: BLE001
                print("Gamepad support unavailable (%s)" % exc)
        self.pad_keys = {  # gamepad action -> the keyboard key it triggers
            "pause": glfw.KEY_SPACE,
            "recenter": glfw.KEY_R,
            "seek_back": glfw.KEY_LEFT,
            "seek_fwd": glfw.KEY_RIGHT,
            "vol_up": glfw.KEY_UP,
            "vol_down": glfw.KEY_DOWN,
            "long_back": glfw.KEY_PAGE_DOWN,
            "long_fwd": glfw.KEY_PAGE_UP,
            "stereo": glfw.KEY_S,
            "position": glfw.KEY_V,
            "mute": glfw.KEY_M,
            # Overlay navigation (used when the settings overlay is open)
            "menu_up": glfw.KEY_UP,
            "menu_down": glfw.KEY_DOWN,
            "menu_left": glfw.KEY_LEFT,
            "menu_right": glfw.KEY_RIGHT,
        }
        self.cmd_queue = queue.Queue()
        self.last_state = 0.0
        if getattr(args, "control", False):
            self._start_control()
        self._init_window()
        self._init_gl()
        self._init_mpv()

    _DK2_NAME_HINTS = ("oculus", "dk2", "rift")

    # ---------------- setup ----------------
    def _init_window(self):
        glfw.init()
        monitors = glfw.get_monitors()
        primary = glfw.get_primary_monitor()
        mon = None
        if self.args.monitor is not None:
            mon = monitors[self.args.monitor]
        elif not self.args.windowed:
            # Prefer a monitor whose name mentions Oculus/DK2/Rift, then any
            # non-primary 1920x1080 monitor as fallback.
            dk2_mon = None
            fallback_mon = None
            for m in monitors:
                if m == primary:
                    continue
                vm = glfw.get_video_mode(m)
                if {vm.size.width, vm.size.height} != {1920, 1080}:
                    continue
                name = glfw.get_monitor_name(m).decode(errors="replace").lower()
                if any(h in name for h in self._DK2_NAME_HINTS):
                    dk2_mon = m
                    break
                if fallback_mon is None:
                    fallback_mon = m
            mon = dk2_mon or fallback_mon
            if mon is None:
                print(
                    "No DK2-sized secondary monitor found -> windowed preview "
                    "(use --monitor N to force one, --list-monitors to see them)."
                )
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        glfw.window_hint(glfw.AUTO_ICONIFY, glfw.FALSE)
        if mon is not None:
            vm = glfw.get_video_mode(mon)
            glfw.window_hint(glfw.REFRESH_RATE, vm.refresh_rate)
            name = glfw.get_monitor_name(mon).decode(errors="replace")
            is_primary = mon == primary
            print(
                "Using monitor %s (%dx%d @ %d Hz%s)"
                % (
                    name,
                    vm.size.width,
                    vm.size.height,
                    vm.refresh_rate,
                    "  [PRIMARY]" if is_primary else "",
                )
            )
            self.win = glfw.create_window(
                vm.size.width, vm.size.height, "Bluehour", mon, None
            )
        else:
            self.win = glfw.create_window(1600, 900, "Bluehour (preview)", None, None)
        if not self.win:
            raise SystemExit("Could not create an OpenGL 3.3 window.")
        glfw.make_context_current(self.win)
        glfw.swap_interval(1)
        glfw.set_input_mode(self.win, glfw.CURSOR, glfw.CURSOR_DISABLED)
        glfw.set_key_callback(self.win, self._on_key)
        glfw.set_cursor_pos_callback(self.win, self._on_cursor)

    def _program(self, frag):
        from OpenGL.GL import shaders

        return shaders.compileProgram(
            shaders.compileShader(VERT, gl.GL_VERTEX_SHADER),
            shaders.compileShader(frag, gl.GL_FRAGMENT_SHADER),
        )

    def _init_gl(self):
        self.vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(self.vao)
        self.eye_prog = self._program(EYE_FRAG)
        self.present_prog = self._program(PRESENT_FRAG)
        self.u = {
            n: gl.glGetUniformLocation(self.eye_prog, n)
            for n in (
                "uVideo",
                "uRot",
                "uEye",
                "uProj",
                "uStereo",
                "uSwap",
                "uAspect",
                "uScreenW",
                "uDist",
                "uTanHalf",
                "uVpAspect",
                "uIpd",
                "uCA",
                "uPos",
                "uK",
            )
        }
        self.pu = {
            n: gl.glGetUniformLocation(self.present_prog, n)
            for n in ("uTex", "uRotate")
        }
        self._make_video_fbo(1920, 1080)

    def _make_fbo(self, w, h):
        tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_RGBA8,
            w,
            h,
            0,
            gl.GL_RGBA,
            gl.GL_UNSIGNED_BYTE,
            None,
        )
        for p, v in (
            (gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
            (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
            (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
            (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE),
        ):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, p, v)
        fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, tex, 0
        )
        return fbo, tex

    def _make_video_fbo(self, w, h):
        if self.vfbo is not None:
            gl.glDeleteFramebuffers(1, [self.vfbo])
            gl.glDeleteTextures(1, [self.vtex])
        self.vw, self.vh = w, h
        self.vfbo, self.vtex = self._make_fbo(w, h)

    def _init_mpv(self):
        import ctypes

        player = mpv.MPV(
            vo="libmpv",
            hwdec=self.args.hwdec,
            input_default_bindings=False,
            input_vo_keyboard=False,
            osc=False,
            ytdl=True,
            keep_open="yes",
        )
        player["osd-level"] = 1
        if self.args.audio_device:
            player["audio-device"] = self.args.audio_device
        self.player = player

        def get_proc_address(_, name):
            addr = glfw.get_proc_address(name.decode("utf-8"))
            return ctypes.cast(addr, ctypes.c_void_p).value

        self._proc = mpv.MpvGlGetProcAddressFn(get_proc_address)
        self.ctx = mpv.MpvRenderContext(
            player, "opengl", opengl_init_params={"get_proc_address": self._proc}
        )
        player.volume = self.args.volume
        player.loadfile(self.files[0])
        for f in self.files[1:]:
            player.loadfile(f, "append")

    # ---------------- input ----------------
    def _on_cursor(self, win, x, y):
        if self.last_cursor is not None and isinstance(self.tracker, MouseTracker):
            self.tracker.add(x - self.last_cursor[0], y - self.last_cursor[1])
        self.last_cursor = (x, y)

    def _on_key(self, win, key, scancode, action, mods):
        if action == glfw.RELEASE:
            return
        # Route keys to the in-headset overlay when it is open.
        if self.overlay.visible:
            if self.overlay.key(key):
                return
        K = glfw
        p = self.player
        if key in (K.KEY_ESCAPE, K.KEY_Q):
            glfw.set_window_should_close(win, True)
        elif key == K.KEY_SPACE:
            p.pause = not p.pause
        elif key == K.KEY_LEFT:
            p.command("seek", -10)
        elif key == K.KEY_RIGHT:
            p.command("seek", 10)
        elif key == K.KEY_PAGE_UP:
            p.command("seek", 60)
        elif key == K.KEY_PAGE_DOWN:
            p.command("seek", -60)
        elif key == K.KEY_UP:
            p.volume = min(130, (p.volume or 0) + 5)
        elif key == K.KEY_DOWN:
            p.volume = max(0, (p.volume or 0) - 5)
        elif key == K.KEY_M:
            p.mute = not p.mute
        elif key == K.KEY_N:
            p.command("playlist-next")
        elif key == K.KEY_P:
            p.command("playlist-prev")
        elif key == K.KEY_T:
            p.command("cycle", "sub")
        elif key == K.KEY_A:
            p.command("cycle", "audio")
        elif key == K.KEY_R:
            self.tracker.recenter()
            if self.camera is not None:
                self.camera.recenter()
            if self.wii_pos is not None:
                self.wii_pos.recenter()
            if self.wii_ctl is not None:
                self.wii_ctl.rumble(0.1)
        elif key == K.KEY_V:
            self.pos_mode = (self.pos_mode + 1) % len(POS_NAMES)
        elif key == K.KEY_1:
            self.proj = 0
        elif key == K.KEY_2:
            self.proj = 1
        elif key == K.KEY_3:
            self.proj = 2
        elif key == K.KEY_4:
            self.proj = 3
        elif key == K.KEY_S:
            self.stereo = (self.stereo + 1) % 3
        elif key == K.KEY_X:
            self.swap ^= 1
        elif key == K.KEY_F:
            self.rotate = (self.rotate + 1) % 4
        elif key == K.KEY_MINUS:
            self.screen_w = max(0.5, self.screen_w / 1.1)
        elif key == K.KEY_EQUAL:
            self.screen_w = min(40.0, self.screen_w * 1.1)
        elif key == K.KEY_9:
            self.dist = max(0.5, self.dist / 1.1)
        elif key == K.KEY_0:
            self.dist = min(30.0, self.dist * 1.1)
        elif key == K.KEY_LEFT_BRACKET:
            self.ipd = max(0.050, self.ipd - 0.001)
        elif key == K.KEY_RIGHT_BRACKET:
            self.ipd = min(0.075, self.ipd + 0.001)
        elif key == K.KEY_SEMICOLON:
            self.tan_half = max(0.4, self.tan_half - 0.02)
        elif key == K.KEY_APOSTROPHE:
            self.tan_half = min(1.6, self.tan_half + 0.02)
        elif key == K.KEY_COMMA:
            self.k[1] = round(self.k[1] - 0.01, 3)
        elif key == K.KEY_PERIOD:
            self.k[1] = round(self.k[1] + 0.01, 3)
        elif key == K.KEY_H:
            print(HELP)
            return
        elif key == K.KEY_G:
            self.overlay.toggle()
            return
        else:
            return
        print(self.status())

    def _on_pad_action(self, action):
        if self.overlay.visible and action == "recenter":
            self.overlay.toggle()
            return
        if action == "proj":  # cycle projection: flat -> curved -> VR180 -> VR360
            self.proj = (self.proj + 1) % len(PROJ_NAMES)
            print(self.status())
            return
        key = self.pad_keys.get(action)
        if key is not None:
            self._on_key(self.win, key, 0, glfw.PRESS, 0)

    def _on_wii_button(self, name):
        if name == "two":  # cycle projection: flat -> curved -> VR180 -> VR360
            self.proj = (self.proj + 1) % len(PROJ_NAMES)
            print(self.status())
            return
        key = self.wii_keys.get(name)
        if key is not None:
            self._on_key(self.win, key, 0, glfw.PRESS, 0)

    # ---------------- live control (used by the GUI) ----------------
    def _start_control(self):
        def reader():
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.cmd_queue.put(control.parse_command(line))
                except ValueError as exc:
                    print("control: ignored command (%s)" % exc, flush=True)
            self.cmd_queue.put(
                {"cmd": "quit"}
            )  # the GUI closed the pipe: shut down with it

        threading.Thread(target=reader, daemon=True).start()

    def _current_path(self):
        try:
            return self.player.path or self.files[0]
        except Exception:  # noqa: BLE001
            return self.files[0]

    def _apply_set(self, name, value):
        if name == "proj":
            self.proj = (
                guess_layout(self._current_path())[0]
                if value == "auto"
                else PROJ_NAMES.index(value)
            )
        elif name == "stereo":
            self.stereo = (
                guess_layout(self._current_path())[1]
                if value == "auto"
                else STEREO_NAMES.index(value)
            )
        elif name == "swap_eyes":
            self.swap = int(value)
        elif name == "rotate":
            self.rotate = ROTATE_NAMES.index(value)
        elif name == "screen_width":
            self.screen_w = value
        elif name == "distance":
            self.dist = value
        elif name == "ipd":
            self.ipd = value / 1000.0
        elif name == "fov_scale":
            self.tan_half = value
        elif name == "k":
            self.k = list(value)
        elif name == "ca":
            self.ca = value
        elif name == "position":
            self.pos_mode = POS_NAMES.index(value)
        elif name == "move_scale":
            self.pos_scale = value
        elif name == "volume":
            self.player.volume = value
        elif name == "pause":
            self.player.pause = value
        elif name == "mute":
            self.player.mute = value

    def _apply_command(self, cmd):
        kind = cmd["cmd"]
        if kind == "action":
            self._on_key(
                self.win,
                getattr(glfw, "KEY_" + control.ACTION_KEYS[cmd["name"]]),
                0,
                glfw.PRESS,
                0,
            )
        elif kind == "set":
            self._apply_set(cmd["name"], cmd["value"])
        elif kind == "seek":
            self.player.command("seek", cmd["value"], cmd["mode"])
        elif kind == "load":
            files = cmd["files"]
            if cmd["mode"] == "replace":
                self.player.loadfile(files[0])
                for f in files[1:]:
                    self.player.loadfile(f, "append")
                self.files = list(files)
                if not self.args.proj:
                    self.proj = guess_layout(files[0])[0]
                if not self.args.stereo:
                    self.stereo = guess_layout(files[0])[1]
            else:
                for f in files:
                    self.player.loadfile(f, "append")
                self.files.extend(files)
        elif kind == "play_index":
            self.player.playlist_pos = cmd["index"]
        elif kind == "quit":
            glfw.set_window_should_close(self.win, True)

    def _drain_commands(self):
        while True:
            try:
                cmd = self.cmd_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._apply_command(cmd)
            except (
                Exception
            ) as exc:  # noqa: BLE001 - a bad command must never stop playback
                print("control: command failed (%s)" % exc, flush=True)

    def _prop(self, name, default=None):
        try:
            value = getattr(self.player, name)
        except Exception:  # noqa: BLE001
            return default
        return default if value is None else value

    def state(self):
        playlist = []
        try:
            playlist = [
                os.path.basename(str(e.get("filename", "")))
                for e in self.player.playlist
            ][:200]
        except Exception:  # noqa: BLE001
            pass
        return {
            "pause": bool(self._prop("pause", False)),
            "mute": bool(self._prop("mute", False)),
            "time": float(self._prop("time_pos", 0.0)),
            "duration": float(self._prop("duration", 0.0)),
            "volume": float(self._prop("volume", 0.0)),
            "file": os.path.basename(str(self._prop("path", ""))),
            "index": int(self._prop("playlist_pos", 0)),
            "playlist": playlist,
            "proj": PROJ_NAMES[self.proj],
            "stereo": STEREO_NAMES[self.stereo],
            "swap_eyes": bool(self.swap),
            "rotate": ROTATE_NAMES[self.rotate],
            "screen_width": self.screen_w,
            "distance": self.dist,
            "ipd": round(self.ipd * 1000.0, 2),
            "fov_scale": round(self.tan_half, 3),
            "k": list(self.k),
            "ca": self.ca,
            "position": POS_NAMES[self.pos_mode],
            "position_now": self.pos_src,
            "move_scale": self.pos_scale,
            "head_tracker": (
                "dk2" if type(self.tracker).__name__ == "DK2Tracker" else "mouse"
            ),
            "wii_controller": self.wii_ctl is not None,
            "wii_camera": self.wii_cam is not None,
            "camera": self.camera is not None,
            "gamepads": len(self.pad.devices) if self.pad is not None else 0,
        }

    def _emit_state(self, now):
        if getattr(self.args, "control", False) and now - self.last_state >= 0.4:
            self.last_state = now
            print(control.encode_state(self.state()), flush=True)

    def status(self):
        return (
            "[%s | %s%s | screen %.1f m @ %.1f m | ipd %.0f mm | fov %.2f | k1 %.2f | rotate %d | "
            "position %s (now: %s)]"
            % (
                PROJ_NAMES[self.proj],
                STEREO_NAMES[self.stereo],
                " swapped" if self.swap else "",
                self.screen_w,
                self.dist,
                self.ipd * 1000,
                self.tan_half,
                self.k[1],
                self.rotate * 90,
                POS_NAMES[self.pos_mode],
                self.pos_src,
            )
        )

    # ---------------- rendering ----------------
    def head_position(self, q):
        """Head position in metres for the current position mode (flat / curved screens use it)."""
        mode = POS_NAMES[self.pos_mode]
        src = mode
        if mode == "auto":
            if self.camera is not None and self.camera.healthy():
                src = "camera"
            elif self.wii_pos is not None and self.wii_pos.healthy():
                src = "wii"
            else:
                src = "neck"
        if src == "camera" and self.camera is not None:
            p = q_rot(self.tracker.offset_quat(), self.camera.position())
        elif src == "wii" and self.wii_pos is not None:
            p = q_rot(self.tracker.offset_quat(), self.wii_pos.position())
        elif src == "neck":
            p = q_rot(q, NECK) - NECK
        else:
            src, p = "none", np.zeros(3)
        self.pos_src = src
        return p * self.pos_scale

    def _eye_aspect(self):
        a = self.vw / float(self.vh)
        if self.stereo == 1:
            return a / 2.0 if a > 2.7 else a  # full SBS vs. half (anamorphic) SBS
        if self.stereo == 2:
            return a * 2.0 if a < 1.2 else a  # full OU vs. half OU
        return a

    def _sync_video_size(self):
        try:
            dw, dh = self.player.dwidth, self.player.dheight
        except Exception:  # noqa: BLE001
            return
        if not dw or not dh:
            return
        scale = min(1.0, 4096.0 / dw)
        w, h = max(16, int(dw * scale)), max(16, int(dh * scale))
        if (w, h) != (self.vw, self.vh):
            self._make_video_fbo(w, h)

    def _render_video(self):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.vfbo)
        fbo = {"w": self.vw, "h": self.vh, "fbo": int(self.vfbo)}
        try:
            self.ctx.render(opengl_fbo=fbo, flip_y=True, block_for_target_time=False)
        except TypeError:
            self.ctx.render(opengl_fbo=fbo, flip_y=True)

    def _ensure_offscreen(self, fbw, fbh):
        size = (fbw, fbh) if fbw >= fbh else (fbh, fbw)
        if size != self.osize:
            if self.ofbo is not None:
                gl.glDeleteFramebuffers(1, [self.ofbo])
                gl.glDeleteTextures(1, [self.otex])
            self.ofbo, self.otex = self._make_fbo(*size)
            self.osize = size

    def _draw_eyes(self):
        ew, eh = self.osize
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.ofbo)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glBindVertexArray(self.vao)
        gl.glUseProgram(self.eye_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.vtex)
        q = self.tracker.orientation()
        rot = np.ascontiguousarray(q_mat(q), dtype=np.float32)
        pos = self.head_position(q)
        u = self.u
        gl.glUniform3f(u["uPos"], float(pos[0]), float(pos[1]), float(pos[2]))
        gl.glUniform1i(u["uVideo"], 0)
        gl.glUniformMatrix3fv(u["uRot"], 1, gl.GL_TRUE, rot)
        gl.glUniform1i(u["uProj"], self.proj)
        gl.glUniform1i(u["uStereo"], self.stereo)
        gl.glUniform1i(u["uSwap"], self.swap)
        gl.glUniform1f(u["uAspect"], self._eye_aspect())
        gl.glUniform1f(u["uScreenW"], self.screen_w)
        gl.glUniform1f(u["uDist"], self.dist)
        gl.glUniform1f(u["uTanHalf"], self.tan_half)
        gl.glUniform1f(u["uVpAspect"], (ew / 2.0) / eh)
        gl.glUniform1f(u["uIpd"], self.ipd)
        gl.glUniform1f(u["uCA"], self.ca)
        gl.glUniform4f(u["uK"], *self.k)
        for eye, x in ((-1.0, 0), (1.0, ew // 2)):
            gl.glViewport(x, 0, ew // 2, eh)
            gl.glUniform1f(u["uEye"], eye)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        self.overlay.draw(ew, eh)

    def _present(self, fbw, fbh):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glViewport(0, 0, fbw, fbh)
        gl.glUseProgram(self.present_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.otex)
        gl.glUniform1i(self.pu["uTex"], 0)
        gl.glUniform1i(self.pu["uRotate"], self.rotate)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

    def run(self):
        print(HELP)
        print(self.status())
        first = True
        try:
            while not glfw.window_should_close(self.win):
                glfw.poll_events()
                self._drain_commands()
                self._emit_state(time.time())
                if self.wii_ctl is not None:
                    for ev in self.wii_ctl.pop_events():
                        self._on_wii_button(ev)
                if self.pad is not None:
                    for action in self.pad.poll():
                        self._on_pad_action(action)
                fbw, fbh = glfw.get_framebuffer_size(self.win)
                if fbw < 8 or fbh < 8:
                    time.sleep(0.05)
                    continue
                self._sync_video_size()
                if self.ctx.update() or first:
                    self._render_video()
                    first = False
                self._ensure_offscreen(fbw, fbh)
                self._draw_eyes()
                self._present(fbw, fbh)
                glfw.swap_buffers(self.win)
                try:
                    self.ctx.report_swap()
                except Exception:  # noqa: BLE001
                    pass
                if (
                    self.player.core_idle
                    and self.player.eof_reached
                    and len(self.files) == 1
                ):
                    pass  # keep-open: stay on the last frame
        finally:
            self.tracker.close()
            if self.camera is not None:
                self.camera.close()
            for remote in (self.wii_ctl, self.wii_cam):
                if remote is not None:
                    remote.close()
            try:
                self.ctx.free()
                self.player.terminate()
            except Exception:  # noqa: BLE001
                pass
            glfw.terminate()


glfw = gl = mpv = (
    None  # imported lazily in main() so --help and the test modes work without them
)

HELP = """
Bluehour controls
  Space pause      Left/Right seek 10 s     PgUp/PgDn seek 60 s     Up/Down volume     M mute
  N / P next/prev  T subtitles              A audio track           R recenter view    Esc quit
  1 flat  2 curved  3 VR180  4 VR360        S cycle mono/SBS/OU     X swap eyes
  - / =  screen size     9 / 0  screen distance     [ / ]  IPD     ; / '  FOV scale
  , / .  lens distortion (k1)               F  rotate output (for portrait / flipped DK2 display)
  V  cycle position source: auto / camera / wii / neck / none  (leaning + moving: flat / curved screens)
  H show this help

USB gamepad (Xbox / PlayStation style; others via --pad-config):
  A pause   B recenter   X cycle mono/SBS/OU   Y cycle flat/curved/VR180/VR360
  D-pad L/R seek 10 s, U/D volume   LB/RB seek 60 s   Back mute   Start cycle position source

Wii Remote (held upright, pointing at nothing in particular - it is only a remote):
  A pause   B recenter (+ buzz)   D-pad L/R seek 10 s, U/D volume   +/- seek 60 s
  1 cycle mono/SBS/OU   2 cycle flat/curved/VR180/VR360   Home cycle position source
"""


def build_parser():
    ap = argparse.ArgumentParser(
        prog="bluehour", description="VR media player for the Oculus Rift DK2"
    )
    ap.add_argument("--version", action="version", version="bluehour " + __version__)
    ap.add_argument(
        "files", nargs="*", help="video files or URLs (a file dialog opens if omitted)"
    )
    ap.add_argument(
        "--proj",
        choices=PROJ_NAMES,
        help="projection (default: guessed from file name)",
    )
    ap.add_argument(
        "--stereo",
        choices=STEREO_NAMES,
        help="3D layout (default: guessed from file name)",
    )
    ap.add_argument("--swap-eyes", action="store_true")
    ap.add_argument("--tracking", choices=["auto", "dk2", "mouse"], default="auto")
    ap.add_argument(
        "--axis-map",
        default="x,y,z",
        help="sensor axis remap, e.g. '-x,y,-z' (see README)",
    )
    ap.add_argument("--monitor", type=int, help="monitor index to go fullscreen on")
    ap.add_argument(
        "--windowed", action="store_true", help="show a side-by-side preview window"
    )
    ap.add_argument("--list-monitors", action="store_true")
    ap.add_argument("--rotate", choices=["none", "cw", "flip", "ccw"], default="none")
    ap.add_argument("--screen-width", type=float, default=4.0)
    ap.add_argument("--distance", type=float, default=3.0)
    ap.add_argument("--ipd", type=float, default=63.5, help="mm")
    ap.add_argument("--fov-scale", type=float, default=0.9)
    ap.add_argument(
        "--k",
        type=float,
        nargs=4,
        default=[1.0, 0.22, 0.24, 0.0],
        metavar=("K0", "K1", "K2", "K3"),
    )
    ap.add_argument(
        "--ca",
        type=float,
        default=0.005,
        help="chromatic aberration correction (0 = off)",
    )
    ap.add_argument(
        "--position",
        choices=POS_NAMES,
        default="auto",
        help="positional tracking source: auto = DK2 camera when it sees the LEDs, else neck model",
    )
    ap.add_argument(
        "--move-scale",
        type=float,
        default=1.0,
        help="multiply head movement (1.0 = real size)",
    )
    ap.add_argument(
        "--camera",
        type=int,
        help="camera index (default: auto-detect a 752x480 camera)",
    )
    ap.add_argument(
        "--cam-fov",
        type=float,
        default=74.0,
        help="camera horizontal field of view, degrees",
    )
    ap.add_argument(
        "--cam-distance",
        type=float,
        default=1.0,
        help="distance in metres between camera and headset when you press R (default 1.0)",
    )
    ap.add_argument(
        "--cam-threshold",
        type=int,
        default=180,
        help="brightness (0-255) that counts as an LED",
    )
    ap.add_argument(
        "--cam-axis-map",
        default="x,y,z",
        help="remap camera position axes, e.g. '-x,y,z'",
    )
    ap.add_argument(
        "--no-led-enable",
        action="store_true",
        help="do not send the LED-enable report to the DK2",
    )
    ap.add_argument("--list-cameras", action="store_true", help="list cameras and exit")
    ap.add_argument(
        "--cam-test",
        action="store_true",
        help="camera preview + tracking numbers, no video",
    )
    ap.add_argument(
        "--wii",
        choices=["auto", "controller", "camera", "both", "off"],
        default="auto",
        help="Wii Remote use: auto = 1 remote -> controller, 2+ -> controller + IR camera",
    )
    ap.add_argument(
        "--wii-swap",
        action="store_true",
        help="swap which remote is the controller / camera",
    )
    ap.add_argument(
        "--wii-ir-level",
        type=int,
        choices=range(1, 6),
        default=3,
        help="IR sensitivity 1-5",
    )
    ap.add_argument(
        "--wii-fov",
        type=float,
        default=45.0,
        help="Wii Remote IR camera field of view, degrees",
    )
    ap.add_argument(
        "--wii-distance",
        type=float,
        default=1.0,
        help="distance in metres between the Wii Remote and the headset when you press R",
    )
    ap.add_argument(
        "--wii-axis-map", default="x,y,z", help="remap Wii position axes, e.g. 'x,-y,z'"
    )
    ap.add_argument(
        "--wii-test",
        action="store_true",
        help="Wii Remote check: buttons, IR points, position",
    )
    ap.add_argument(
        "--no-gamepad",
        action="store_true",
        help="ignore USB gamepads / classic-controller adapters",
    )
    ap.add_argument(
        "--pad-config",
        action="store_true",
        help="teach the player a controller's buttons, then exit",
    )
    ap.add_argument(
        "--pad-test",
        action="store_true",
        help="show what connected controllers send, then exit",
    )
    ap.add_argument(
        "--pad-file", help="gamepad mapping file (default: per-user config folder)"
    )
    ap.add_argument(
        "--pad-deadzone", type=float, default=0.15, help="gamepad stick deadzone (0-1)"
    )
    ap.add_argument("--hwdec", default="auto-safe")
    ap.add_argument(
        "--audio-device", help="mpv audio device name (mpv --audio-device=help)"
    )
    ap.add_argument("--volume", type=float, default=80)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument(
        "--doctor",
        action="store_true",
        help="check Python packages, libmpv, the DK2, Wii Remotes and controllers, then exit",
    )
    # JSON commands on stdin, state lines on stdout: used by the GUI
    ap.add_argument("--control", action="store_true", help=argparse.SUPPRESS)
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()

    prepare_library_path()
    if args.doctor:
        from . import doctor

        raise SystemExit(doctor.run())
    if args.list_cameras:
        list_cameras()
        return
    if args.wii_test:
        wii_test(args)
        return
    if args.pad_config or args.pad_test:
        try:
            import glfw as _g
            from . import gamepad
        except ImportError as exc:
            raise SystemExit(
                "Missing dependency: %s (reinstall Bluehour with pip to pull in its dependencies)"
                % exc
            )
        path = args.pad_file or gamepad.default_path()
        (gamepad.run_config if args.pad_config else gamepad.run_test)(_g, path)
        return
    if args.cam_test:
        try:
            camera_test(args)
        except (RuntimeError, ImportError) as exc:
            raise SystemExit("Camera test failed: %s" % exc)
        return

    global glfw, gl, mpv
    import glfw as _glfw
    from OpenGL import GL as _gl

    glfw, gl = _glfw, _gl

    if args.list_monitors:
        glfw.init()
        for i, m in enumerate(glfw.get_monitors()):
            vm = glfw.get_video_mode(m)
            print(
                "%d: %s  %dx%d @ %d Hz%s"
                % (
                    i,
                    glfw.get_monitor_name(m).decode(errors="replace"),
                    vm.size.width,
                    vm.size.height,
                    vm.refresh_rate,
                    "  (primary)" if m == glfw.get_primary_monitor() else "",
                )
            )
        return

    files = args.files
    if not files:
        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            files = list(filedialog.askopenfilenames(title="Choose video(s)"))
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
    if not files:
        ap.error("no video given")

    import mpv as _mpv

    mpv = _mpv

    app = App(args, files)

    # Graceful shutdown: on SIGINT/SIGTERM, request the window close so the
    # run() finally-block closes trackers, HID devices, mpv and GLFW cleanly.
    def _handle_signal(signum, frame):
        try:
            if app.win is not None:
                glfw.set_window_should_close(app.win, True)
        except Exception:  # noqa: BLE001
            pass

    try:
        signal.signal(signal.SIGINT, _handle_signal)
    except (AttributeError, OSError):  # not all platforms/threads support signals
        pass
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (AttributeError, OSError):
        pass

    app.run()


if __name__ == "__main__":
    main()
