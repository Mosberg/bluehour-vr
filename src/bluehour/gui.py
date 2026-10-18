"""In-headset settings overlay GUI.

Renders a semi-transparent panel on top of the VR scene using a small
5x5 bitmap font uploaded as an alpha texture.  The overlay is drawn into
the offscreen eye buffer so it appears in both eyes and is presented with
the video.

Navigation (keyboard):
    G          toggle overlay
    Up/Down    move selection
    Left/Right adjust the current setting
    Escape     close overlay

Navigation (gamepad):
    D-pad / L-stick  move selection & adjust
    A / B            adjust current setting
    START / BACK     toggle overlay

Only "live" settings (those that can change while the player runs) are
adjustable; non-live settings are shown read-only with a restart hint.
"""

from __future__ import annotations

import ctypes

import numpy as np
from OpenGL import GL as gl

from . import control, settings

# ----------------------------------------------------------------------
# 5x5 bitmap font, printable ASCII (32-126).  Each glyph is 5 rows of 5
# pixels, packed into a 32-bit int: row r occupies bits [r*5 : r*5+5].
# ----------------------------------------------------------------------
_FONT_5X5 = [
    0x00000000,  # space
    0x00001010,  # !
    0x00005050,  # "
    0x00005050,  # # (approx)
    0x00005050,  # $
    0x00005050,  # %
    0x00005050,  # &
    0x00001010,  # '
    0x00000804,  # (
    0x00000201,  # )
    0x00005050,  # *
    0x00000414,  # +
    0x00000208,  # ,
    0x00000404,  # -
    0x00000202,  # .
    0x00001080,  # /
    0x00001515,  # 0
    0x00000404,  # 1
    0x00001415,  # 2
    0x00001415,  # 3
    0x00001515,  # 4
    0x00001514,  # 5
    0x00001515,  # 6
    0x00000101,  # 7
    0x00001515,  # 8
    0x00001515,  # 9
    0x00000404,  # :
    0x00000404,  # ;
    0x00000804,  # <
    0x00000404,  # =
    0x00000201,  # >
    0x00000404,  # ?
    0x00001515,  # @
    0x00001515,  # A
    0x00001715,  # B
    0x00000D0D,  # C
    0x00001711,  # D
    0x00001717,  # E
    0x00001717,  # F
    0x00000D15,  # G
    0x00001515,  # H
    0x00001707,  # I
    0x00001515,  # J
    0x00001515,  # K
    0x00001010,  # L
    0x00001515,  # M
    0x00001515,  # N
    0x00000D0D,  # O
    0x00001717,  # P
    0x00000D15,  # Q
    0x00001715,  # R
    0x00001515,  # S
    0x00001707,  # T
    0x00001515,  # U
    0x00000A0A,  # V
    0x00001515,  # W
    0x00001515,  # X
    0x00000A0A,  # Y
    0x00001717,  # Z
    0x00000D10,  # [
    0x00001080,  # backslash
    0x0000010D,  # ]
    0x00000208,  # ^
    0x00000000,  # _
    0x00000201,  # `
    0x00001515,  # a
    0x00001710,  # b
    0x00001510,  # c
    0x00001517,  # d
    0x00001515,  # e
    0x00001710,  # f
    0x00001517,  # g
    0x00001710,  # h
    0x00001707,  # i
    0x00000505,  # j
    0x00001710,  # k
    0x00001707,  # l
    0x00001515,  # m
    0x00001710,  # n
    0x00001510,  # o
    0x00001717,  # p
    0x00001717,  # q
    0x00001510,  # r
    0x00001515,  # s
    0x00001707,  # t
    0x00001515,  # u
    0x00000A0A,  # v
    0x00001515,  # w
    0x00001710,  # x
    0x00000A0A,  # y
    0x00001717,  # z
    0x00000D10,  # {
    0x00001707,  # |
    0x0000010D,  # }
    0x00000208,  # ~
]


def _glyph_bit(ch: int, row: int) -> int:
    """Return the 5-bit pixel row for character code ``ch`` on row ``row``."""
    if 32 <= ch <= 126:
        return (_FONT_5X5[ch - 32] >> (row * 5)) & 0x1F
    return 0


class _FontTexture:
    """Builds an alpha texture atlas from the 5x5 bitmap font."""

    def __init__(self):
        # Atlas layout: 96 glyphs in a row, each 6 px wide (5 + 1 spacing),
        # 7 px tall (5 rows + 2 spacing).
        self.w = 96 * 6
        self.h = 7
        buf = np.zeros((self.h, self.w), dtype=np.uint8)
        for ci in range(96):
            ch = 32 + ci
            gx = ci * 6
            for r in range(5):
                bits = _glyph_bit(ch, r)
                for c in range(5):
                    if bits & (1 << c):
                        buf[r + 1, gx + c] = 255
        self.tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_ALPHA,
            self.w,
            self.h,
            0,
            gl.GL_ALPHA,
            gl.GL_UNSIGNED_BYTE,
            buf.tobytes(),
        )
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)

    def char_width(self) -> float:
        return 6.0 / self.w  # advance in texture space

    def char_height(self) -> float:
        return 7.0 / self.h


class Overlay:
    """In-headset settings overlay.

    Renders a panel of live settings on top of the VR scene.  Drawn into
    the offscreen FBO by :meth:`draw` so it appears in both eyes.
    """

    def __init__(self, app: "App"):
        self.app = app
        self.font = _FontTexture()
        self.visible = False
        self.sel = 0  # index into self.rows
        self.scroll = 0
        self.rows: list[dict] = []
        self._rebuild_rows()

    # ------------------------------------------------------------------
    # Row model
    # ------------------------------------------------------------------
    def _rebuild_rows(self):
        """Build the list of editable rows from settings + player state."""
        app = self.app
        rows: list[dict] = []

        def add(name: str, label: str, live: bool, getter, setter=None):
            rows.append(
                {
                    "name": name,
                    "label": label,
                    "live": live,
                    "getter": getter,
                    "setter": setter,
                }
            )

        # Layout group (live)
        add(
            "proj",
            "Screen type",
            True,
            lambda: settings.PROJ[app.proj],
            lambda v: self._set("proj", settings.PROJ.index(v)),
        )
        add(
            "stereo",
            "3D layout",
            True,
            lambda: settings.STEREO[app.stereo],
            lambda v: self._set("stereo", settings.STEREO.index(v)),
        )
        add(
            "swap_eyes",
            "Swap eyes",
            True,
            lambda: "1" if app.swap else "0",
            lambda v: self._set("swap_eyes", int(v)),
        )
        add(
            "rotate",
            "Rotate output",
            True,
            lambda: settings.ROTATE[app.rotate],
            lambda v: self._set("rotate", settings.ROTATE.index(v)),
        )

        # Screen / lens (live)
        add(
            "screen_width",
            "Screen width (m)",
            True,
            lambda: f"{app.screen_w:.1f}",
            lambda v: self._set("screen_width", float(v)),
        )
        add(
            "distance",
            "Screen distance (m)",
            True,
            lambda: f"{app.dist:.1f}",
            lambda v: self._set("distance", float(v)),
        )
        add(
            "ipd",
            "IPD (mm)",
            True,
            lambda: f"{app.ipd * 1000:.0f}",
            lambda v: self._set("ipd", float(v) / 1000.0),
        )
        add(
            "fov_scale",
            "FOV scale",
            True,
            lambda: f"{app.tan_half:.2f}",
            lambda v: self._set("fov_scale", float(v)),
        )
        add(
            "k",
            "Lens distortion k1",
            True,
            lambda: f"{app.k[1]:.2f}",
            lambda v: self._set("k", [float(x) for x in v.split(",")]),
        )
        add(
            "ca",
            "Chromatic aberration",
            True,
            lambda: f"{app.ca:.3f}",
            lambda v: self._set("ca", float(v)),
        )

        # Playback (live)
        add(
            "pause",
            "Pause",
            True,
            lambda: "1" if app.player.pause else "0",
            lambda v: self._set("pause", v == "1"),
        )
        add(
            "volume",
            "Volume (%)",
            True,
            lambda: f"{app.player.volume:.0f}",
            lambda v: self._set("volume", float(v)),
        )
        add(
            "mute",
            "Mute",
            True,
            lambda: "1" if app.player.mute else "0",
            lambda v: self._set("mute", v == "1"),
        )

        # Position (live)
        add(
            "position",
            "Position source",
            True,
            lambda: settings.POSITION[app.pos_mode],
            lambda v: self._set("position", settings.POSITION.index(v)),
        )
        add(
            "move_scale",
            "Movement scale",
            True,
            lambda: f"{app.pos_scale:.1f}",
            lambda v: self._set("move_scale", float(v)),
        )

        # Non-live (read-only)
        add(
            "tracking",
            "Head tracking",
            False,
            lambda: settings.TRACKING[
                (
                    list(settings.TRACKING).index(app.args.tracking)
                    if app.args.tracking in settings.TRACKING
                    else 0
                )
            ],
        )
        add(
            "windowed",
            "Preview window",
            False,
            lambda: "1" if app.args.windowed else "0",
        )
        add(
            "monitor",
            "Monitor",
            False,
            lambda: str(app.args.monitor if app.args.monitor is not None else -1),
        )

        self.rows = rows
        self.sel = min(self.sel, len(self.rows) - 1) if self.rows else 0

    def _set(self, name: str, value):
        """Apply a setting change via the existing command path."""
        try:
            self.app._apply_set(name, value)
            print(self.app.status())
        except Exception as exc:  # noqa: BLE001
            print(f"gui: failed to set {name}={value}: {exc}")

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def toggle(self):
        self.visible = not self.visible
        if self.visible:
            self._rebuild_rows()
            self.sel = 0
            self.scroll = 0

    def key(self, key: int) -> bool:
        """Handle a key press.  Returns True if the key was consumed."""
        if not self.visible:
            return False
        K = glfw.KEY  # type: ignore[attr-defined]
        import glfw  # local import to avoid circular issues at module load

        if key in (glfw.KEY_ESCAPE, glfw.KEY_Q, glfw.KEY_G):
            self.visible = False
            return True
        if key == glfw.KEY_UP:
            self.sel = max(0, self.sel - 1)
            self._clamp_scroll()
            return True
        if key == glfw.KEY_DOWN:
            self.sel = min(len(self.rows) - 1, self.sel + 1)
            self._clamp_scroll()
            return True
        if key in (glfw.KEY_LEFT, glfw.KEY_RIGHT):
            self._adjust(key == glfw.KEY_RIGHT)
            return True
        if key in (glfw.KEY_MINUS, glfw.KEY_KP_SUBTRACT):
            self._adjust(False)
            return True
        if key in (glfw.KEY_EQUAL, glfw.KEY_KP_ADD):
            self._adjust(True)
            return True
        return False

    def pad_action(self, action: str) -> bool:
        """Handle a gamepad action.  Returns True if consumed."""
        if not self.visible:
            return False
        if action == "recenter":  # BACK / START toggle
            self.toggle()
            return True
        if action == "stereo":  # Up
            self.sel = max(0, self.sel - 1)
            self._clamp_scroll()
            return True
        # We need directional + A/B from gamepad; those come through _on_key
        # when the pad maps them to keys.  Handle the rest here.
        return False

    def pad_axis(self, action: str) -> bool:
        """Handle a gamepad stick directional action.  Returns True if consumed."""
        if not self.visible:
            return False
        if action == "menu_up":
            self.sel = max(0, self.sel - 1)
            self._clamp_scroll()
            return True
        if action == "menu_down":
            self.sel = min(len(self.rows) - 1, self.sel + 1)
            self._clamp_scroll()
            return True
        if action == "menu_left":
            self._adjust(False)
            return True
        if action == "menu_right":
            self._adjust(True)
            return True
        return False

    def _clamp_scroll(self):
        n = len(self.rows)
        show = 10  # rows visible at once
        if self.sel < self.scroll:
            self.scroll = self.sel
        elif self.sel >= self.scroll + show:
            self.scroll = self.sel - show + 1
        self.scroll = max(0, min(self.scroll, max(0, n - show)))

    def _adjust(self, inc: bool):
        row = self.rows[self.sel]
        if not row["live"]:
            return
        # Try numeric step from the settings field
        f = settings.BY_NAME.get(row["name"])
        cur = row["getter"]()
        try:
            cur_val = float(cur)
        except (ValueError, TypeError):
            cur_val = None

        if f is not None and f.kind in ("float", "int") and cur_val is not None:
            step = f.step or 1.0
            new_val = cur_val + (step if inc else -step)
            if f.min is not None:
                new_val = max(f.min, new_val)
            if f.max is not None:
                new_val = min(f.max, new_val)
            if f.kind == "int":
                new_val = int(round(new_val))
            else:
                new_val = round(new_val, 4)
            self._set(row["name"], new_val)
        elif row["name"] in ("pause", "mute", "swap_eyes"):
            self._set(row["name"], "1" if cur != "1" else "0")
        elif row["name"] == "proj":
            vals = settings.PROJ
            idx = vals.index(cur) if cur in vals else 0
            idx = (idx + (1 if inc else -1)) % len(vals)
            self._set(row["name"], vals[idx])
        elif row["name"] == "stereo":
            vals = settings.STEREO
            idx = vals.index(cur) if cur in vals else 0
            idx = (idx + (1 if inc else -1)) % len(vals)
            self._set(row["name"], vals[idx])
        elif row["name"] == "rotate":
            vals = settings.ROTATE
            idx = vals.index(cur) if cur in vals else 0
            idx = (idx + (1 if inc else -1)) % len(vals)
            self._set(row["name"], vals[idx])
        elif row["name"] == "position":
            vals = settings.POSITION
            idx = vals.index(cur) if cur in vals else 0
            idx = (idx + (1 if inc else -1)) % len(vals)
            self._set(row["name"], vals[idx])
        elif row["name"] == "k":
            # adjust k1 only
            try:
                k = list(self.app.k)
                k[1] = round(k[1] + (0.01 if inc else -0.01), 3)
                self._set("k", k)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self, fbw: int, fbh: int):
        """Draw the overlay into the currently bound framebuffer."""
        if not self.visible or not self.rows:
            return
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        # Panel background
        self._draw_rect(0.02, 0.02, 0.42, 0.92, 0.0, 0.0, 0.0, 0.75)
        self._draw_rect(0.02, 0.02, 0.42, 0.05, 0.2, 0.4, 0.8, 0.9)  # header bar

        # Title
        self._draw_text(0.035, 0.04, "BLUEHOUR VR SETTINGS", 0.03, 1.0, 1.0, 1.0, 1.0)

        # Hint line
        self._draw_text(
            0.035,
            0.075,
            "Up/Dn select  Left/Rt adjust  Esc close",
            0.018,
            0.8,
            0.8,
            0.8,
            1.0,
        )

        y = 0.12
        row_h = 0.062
        show = 12
        for i in range(self.scroll, min(self.scroll + show, len(self.rows))):
            row = self.rows[i]
            selected = i == self.sel
            if selected:
                self._draw_rect(0.03, y - 0.018, 0.39, row_h, 0.3, 0.5, 0.7, 0.35)
            live_marker = "*" if row["live"] else " "
            label = f"{live_marker}{row['label']}"
            val = row["getter"]()
            self._draw_text(
                0.04, y, label, 0.022, 1.0, 1.0, 1.0, 1.0 if selected else 0.7
            )
            # Value right-aligned
            val_str = str(val)
            vx = 0.38 - len(val_str) * 0.011
            self._draw_text(
                vx, y, val_str, 0.022, 0.4, 0.9, 1.0, 1.0 if selected else 0.7
            )
            y += row_h

        # Footer
        self._draw_text(
            0.035,
            y + 0.01,
            "* = live (changes while playing)",
            0.016,
            0.6,
            0.6,
            0.6,
            1.0,
        )
        self._draw_text(
            0.035,
            y + 0.025,
            "Non-live settings need a restart",
            0.016,
            0.6,
            0.6,
            0.6,
            1.0,
        )

        gl.glDisable(gl.GL_BLEND)

    # ------------------------------------------------------------------
    # Primitive drawing helpers (orthographic, 0-1 coords)
    # ------------------------------------------------------------------
    def _draw_rect(self, x, y, w, h, r, g, b, a):
        gl.glUseProgram(0)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glOrtho(0, 1, 0, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glColor4f(r, g, b, a)
        gl.glBegin(gl.GL_QUADS)
        gl.glVertex2f(x, y)
        gl.glVertex2f(x + w, y)
        gl.glVertex2f(x + w, y + h)
        gl.glVertex2f(x, y + h)
        gl.glEnd()
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_MODELVIEW)

    def _draw_text(self, x, y, text, scale, r, g, b, a):
        """Draw a string using the 5x5 bitmap font texture."""
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.font.tex)
        gl.glUseProgram(0)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glOrtho(0, 1, 0, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glLoadIdentity()

        gl.glColor4f(r, g, b, a)
        cx = x
        char_w = 0.012 * scale
        char_h = 0.012 * scale
        tex_cw = 6.0 / self.font.w
        tex_ch = 7.0 / self.font.h

        gl.glBegin(gl.GL_QUADS)
        for ch in text:
            code = ord(ch)
            if code < 32 or code > 126:
                cx += char_w
                continue
            ci = code - 32
            u0 = (ci * 6) / self.font.w
            v0 = 1.0 / self.font.h
            u1 = u0 + tex_cw
            v1 = v0 + tex_ch * 5.0
            gl.glTexCoord2f(u0, v0)
            gl.glVertex2f(cx, y)
            gl.glTexCoord2f(u1, v0)
            gl.glVertex2f(cx + char_w, y)
            gl.glTexCoord2f(u1, v1)
            gl.glVertex2f(cx + char_w, y + char_h)
            gl.glTexCoord2f(u0, v1)
            gl.glVertex2f(cx, y + char_h)
            cx += char_w
        gl.glEnd()

        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_MODELVIEW)
