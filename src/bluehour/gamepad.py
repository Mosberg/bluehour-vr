#!/usr/bin/env python3
"""
USB gamepad / classic-controller input for Bluehour, using GLFW's joystick API.

* Controllers GLFW recognises as gamepads (Xbox One / Xbox 360 pads, DualShock/DualSense, many
  others) get a ready-made mapping.
* Anything else (raphnet Classic Controller / Nunchuk / guitar adapters, a PS3 pad without a
  driver that presents it as a gamepad, odd pads) can be taught with:   bluehour --pad-config
  The result is stored in gamepad.json in the per-user config folder, per controller name.
* Check what a controller sends with:   bluehour --pad-test
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .paths import config_dir

ACTIONS = [
    "pause",
    "recenter",
    "seek_back",
    "seek_fwd",
    "vol_up",
    "vol_down",
    "long_back",
    "long_fwd",
    "stereo",
    "proj",
    "position",
    "mute",
]
LABELS = {
    "pause": "PAUSE / PLAY",
    "recenter": "RECENTER view",
    "seek_back": "SEEK BACK 10 s",
    "seek_fwd": "SEEK FORWARD 10 s",
    "vol_up": "VOLUME UP",
    "vol_down": "VOLUME DOWN",
    "long_back": "SEEK BACK 60 s",
    "long_fwd": "SEEK FORWARD 60 s",
    "stereo": "cycle MONO/SBS/OU",
    "proj": "cycle FLAT/CURVED/VR180/VR360",
    "position": "cycle POSITION source",
    "mute": "MUTE",
}
REPEAT = {"seek_back", "seek_fwd", "vol_up", "vol_down"}

# GLFW gamepad button indices: A=0 B=1 X=2 Y=3 LB=4 RB=5 Back=6 Start=7 Guide=8 LS=9 RS=10
# DPad up=11 right=12 down=13 left=14   (PlayStation: Cross=A, Circle=B, Square=X, Triangle=Y)
DEFAULT_GAMEPAD = {
    "pause": "gp:0",
    "recenter": "gp:1",
    "stereo": "gp:2",
    "proj": "gp:3",
    "long_back": "gp:4",
    "long_fwd": "gp:5",
    "mute": "gp:6",
    "position": "gp:7",
    "vol_up": "gp:11",
    "seek_fwd": "gp:12",
    "vol_down": "gp:13",
    "seek_back": "gp:14",
}
HAT_BITS = (1, 2, 4, 8)  # up, right, down, left
AXIS_THRESHOLD = 0.7


def default_path():
    """Per-user config file: bluehour/gamepad.json in the per-user config folder."""
    return os.path.join(config_dir(), "gamepad.json")


def load_config(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(path, config):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)


def inputs_pressed(
    gp_buttons: Optional[Sequence[int]],
    buttons: Sequence[int],
    axes: Sequence[float],
    hats: Sequence[int],
    deadzone: float = AXIS_THRESHOLD,
) -> Set[str]:
    """Set of input specs currently active:
    gp:N (GLFW gamepad button), button:N, hat:H:BIT, axis:N:+ / axis:N:-"""
    s: Set[str] = set()
    for i, v in enumerate(gp_buttons or ()):
        if v:
            s.add("gp:%d" % i)
    for i, v in enumerate(buttons or ()):
        if v:
            s.add("button:%d" % i)
    for h, v in enumerate(hats or ()):
        hv = int(v) if v is not None else 0
        for bit in HAT_BITS:
            if hv & bit:
                s.add("hat:%d:%d" % (h, bit))
    for i, v in enumerate(axes or ()):
        if v > deadzone:
            s.add("axis:%d:+" % i)
        elif v < -deadzone:
            s.add("axis:%d:-" % i)
    return s


class GlfwBackend:
    """Thin adapter over the glfw module so the logic below can be tested without a window."""

    def __init__(self, glfw):
        self.glfw = glfw

    def present_ids(self) -> List[int]:
        g = self.glfw
        return [
            j for j in range(g.JOYSTICK_1, g.JOYSTICK_LAST + 1) if g.joystick_present(j)
        ]

    def name(self, jid: int) -> Optional[str]:
        n = self.glfw.get_joystick_name(jid)
        return n.decode("utf-8", "replace") if isinstance(n, bytes) else n

    def is_gamepad(self, jid: int) -> bool:
        try:
            return bool(self.glfw.joystick_is_gamepad(jid))
        except Exception:  # noqa: BLE001
            return False

    def gamepad_buttons(self, jid: int) -> Optional[List[int]]:
        if not self.is_gamepad(jid):
            return None
        try:
            state = self.glfw.get_gamepad_state(jid)
            return list(state.buttons) if state else None
        except Exception:  # noqa: BLE001
            return None

    def raw(self, jid: int) -> Tuple[List[int], List[float], List[int]]:
        g = self.glfw

        def lst(x):
            if x is None:
                return []
            try:
                return [int(v) for v in x]
            except TypeError:
                return []

        return (
            lst(g.get_joystick_buttons(jid)),
            lst(g.get_joystick_axes(jid)),
            lst(g.get_joystick_hats(jid)),
        )

    def pressed(self, jid: int, deadzone: float = AXIS_THRESHOLD) -> Set[str]:
        buttons, axes, hats = self.raw(jid)
        return inputs_pressed(self.gamepad_buttons(jid), buttons, axes, hats, deadzone)


class GamepadInput:
    """Polls all connected controllers and turns presses into action names."""

    def __init__(
        self,
        backend,
        path=None,
        repeat_delay=0.45,
        repeat_rate=0.15,
        deadzone=AXIS_THRESHOLD,
        say=print,
    ):
        self.b = backend
        self.path = path or default_path()
        self.config = load_config(self.path)
        self.repeat_delay = repeat_delay
        self.repeat_rate = repeat_rate
        self.deadzone = deadzone
        self.say = say
        self.devices = {}
        self.last_scan = -1e9

    def _scan(self, now):
        if now - self.last_scan < 1.0:
            return
        self.last_scan = now
        present = set(self.b.present_ids())
        for jid in [j for j in self.devices if j not in present]:
            self.say("Controller disconnected: %s" % self.devices[jid]["name"])
            del self.devices[jid]
        for jid in sorted(present - set(self.devices)):
            self._add(jid)

    def _add(self, jid):
        name = self.b.name(jid) or ("Controller %d" % jid)
        mapping, how = None, ""
        if name in self.config:
            mapping, how = self.config[name], "saved mapping"
        elif self.b.is_gamepad(jid):
            mapping, how = DEFAULT_GAMEPAD, "default gamepad mapping"
        else:
            self.say(
                "Controller '%s' has no mapping yet: run  bluehour --pad-config" % name
            )
        self.devices[jid] = {
            "jid": jid,
            "name": name,
            "map": mapping,
            "prev": None,
            "held": {},
        }
        if mapping:
            self.say("Controller connected: %s (%s)" % (name, how))

    def poll(self, now=None):
        """Actions triggered since the last call (edges, plus repeats for seek / volume)."""
        now = time.time() if now is None else now
        self._scan(now)
        out = []
        for dev in self.devices.values():
            if dev["map"] is None:
                continue
            cur = self.b.pressed(dev["jid"], self.deadzone)
            prev, dev["prev"] = dev["prev"], cur
            if prev is None:
                continue  # ignore anything already held when it was connected
            held = dev["held"]
            for action, spec in dev["map"].items():
                down = spec in cur
                if down and spec not in prev:
                    out.append(action)
                    held[action] = [now, now]
                elif down and action in REPEAT:
                    t0, tl = held.get(action, [now, now])
                    if now - t0 > self.repeat_delay and now - tl > self.repeat_rate:
                        out.append(action)
                        held[action] = [t0, now]
                elif not down:
                    held.pop(action, None)
        return out


# ---------------------------------------------------------------------------------------
# Learning a mapping
# ---------------------------------------------------------------------------------------


def first_raw_press(backend, jid, rest_axes):
    """First raw control that is currently active, as a spec string (axes are judged against rest)."""
    buttons, axes, hats = backend.raw(jid)
    for i, v in enumerate(buttons):
        if v:
            return "button:%d" % i
    for h, v in enumerate(hats):
        for bit in HAT_BITS:
            if v & bit:
                return "hat:%d:%d" % (h, bit)
    for i, v in enumerate(axes):
        rest = rest_axes[i] if i < len(rest_axes) else 0.0
        d = v - rest
        if abs(d) > 0.8:
            return "axis:%d:%s" % (i, "+" if d > 0 else "-")
    return None


def learn_mapping(
    backend, jid, say=print, now_fn=time.time, sleep_fn=time.sleep, timeout=12.0
):
    rest = list(backend.raw(jid)[1])
    mapping = {}
    for action in ACTIONS:
        say(
            "Press the control for: %s   (wait %d s to skip)"
            % (LABELS[action], int(timeout))
        )
        idle = 0
        t0 = now_fn()
        while idle < 3 and now_fn() - t0 < 5.0:  # wait until everything is released
            idle = idle + 1 if first_raw_press(backend, jid, rest) is None else 0
            sleep_fn(0.01)
        spec = None
        t0 = now_fn()
        while now_fn() - t0 < timeout:
            spec = first_raw_press(backend, jid, rest)
            if spec:
                break
            sleep_fn(0.01)
        if spec is None:
            say("   skipped")
        elif spec in mapping.values():
            say("   %s is already used for another action - skipped" % spec)
        else:
            mapping[action] = spec
            say("   -> %s" % spec)
    return mapping


def run_config(glfw, path=None):
    """Interactive: pick a controller by pressing something on it, then teach every action."""
    path = path or default_path()
    if not glfw.init():
        raise SystemExit("Could not initialise GLFW.")
    backend = GlfwBackend(glfw)
    print("Press any button on the controller you want to set up (Ctrl+C to abort)...")
    jid = None
    rests = {}
    try:
        while jid is None:
            glfw.poll_events()
            for j in backend.present_ids():
                rests.setdefault(j, list(backend.raw(j)[1]))
                if first_raw_press(backend, j, rests[j]):
                    jid = j
                    break
            time.sleep(0.02)
        name = backend.name(jid) or ("Controller %d" % jid)
        print("Using: %s" % name)
        mapping = learn_mapping(backend, jid)
        if not mapping:
            print("Nothing was mapped; config unchanged.")
            return
        config = load_config(path)
        config[name] = mapping
        save_config(path, config)
        print("Saved %d mappings for '%s' to %s" % (len(mapping), name, path))
    except KeyboardInterrupt:
        print("Aborted.")
    finally:
        glfw.terminate()


def run_test(glfw, path=None):
    """Show controllers, the raw specs they send, and the actions the current mapping triggers."""
    path = path or default_path()
    if not glfw.init():
        raise SystemExit("Could not initialise GLFW.")
    backend = GlfwBackend(glfw)
    pad = GamepadInput(backend, path)
    print(
        "Controller test. Press buttons / move sticks; Ctrl+C quits. Config file: %s"
        % path
    )
    last = {}
    try:
        while True:
            glfw.poll_events()
            for action in pad.poll():
                print("   action: %s" % action)
            for jid in backend.present_ids():
                cur = backend.pressed(jid)
                if cur != last.get(jid):
                    print(
                        "[%s] pressed: %s"
                        % (backend.name(jid), ", ".join(sorted(cur)) or "-")
                    )
                    last[jid] = cur
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        glfw.terminate()
