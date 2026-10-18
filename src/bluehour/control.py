"""The live-control protocol between the GUI and a running player: JSON lines on stdin, `@state` lines on stdout.

Standard library only. The player applies commands in its render loop; this module only validates them.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from . import settings

STATE_PREFIX = "@state "

# Named actions: the keyboard key each one presses inside the player (glfw key name without the KEY_ prefix).
ACTION_KEYS = {
    "pause": "SPACE",
    "seek_back": "LEFT",
    "seek_fwd": "RIGHT",
    "long_back": "PAGE_DOWN",
    "long_fwd": "PAGE_UP",
    "vol_up": "UP",
    "vol_down": "DOWN",
    "mute": "M",
    "next": "N",
    "prev": "P",
    "subtitles": "T",
    "audio": "A",
    "recenter": "R",
    "position": "V",
    "flat": "1",
    "curved": "2",
    "vr180": "3",
    "vr360": "4",
    "stereo": "S",
    "swap": "X",
    "rotate": "F",
    "size_down": "MINUS",
    "size_up": "EQUAL",
    "distance_down": "9",
    "distance_up": "0",
    "ipd_down": "LEFT_BRACKET",
    "ipd_up": "RIGHT_BRACKET",
    "fov_down": "SEMICOLON",
    "fov_up": "APOSTROPHE",
    "k_down": "COMMA",
    "k_up": "PERIOD",
}
# Extra live settings beyond settings.LIVE
PLAYER_SETTINGS = {"pause": bool, "mute": bool}


def parse_command(line: str) -> Dict[str, Any]:
    """Turn one stdin line into a validated command dict, or raise ValueError."""
    try:
        cmd = json.loads(line)
    except ValueError:
        raise ValueError("not JSON") from None
    if not isinstance(cmd, dict) or not isinstance(cmd.get("cmd"), str):
        raise ValueError("a command needs a 'cmd' field")
    kind = cmd["cmd"]
    if kind == "action":
        if cmd.get("name") not in ACTION_KEYS:
            raise ValueError("unknown action: %s" % cmd.get("name"))
        return {"cmd": "action", "name": cmd["name"]}
    if kind == "set":
        name = cmd.get("name")
        value = cmd.get("value")
        if name in PLAYER_SETTINGS:
            if not isinstance(value, bool):
                raise ValueError("%s must be true or false" % name)
            return {"cmd": "set", "name": name, "value": value}
        if name not in settings.LIVE:
            raise ValueError("%s cannot be changed while playing" % name)
        return {"cmd": "set", "name": name, "value": settings.coerce(name, value)}
    if kind == "seek":
        value = cmd.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value != value
        ):
            raise ValueError("seek needs a number of seconds")
        mode = cmd.get("mode", "absolute")
        if mode not in ("absolute", "relative"):
            raise ValueError("seek mode must be absolute or relative")
        return {"cmd": "seek", "value": float(value), "mode": mode}
    if kind == "load":
        files = cmd.get("files")
        mode = cmd.get("mode", "replace")
        if (
            not isinstance(files, list)
            or not files
            or not all(isinstance(f, str) and f for f in files)
        ):
            raise ValueError("load needs a list of files")
        if mode not in ("replace", "append"):
            raise ValueError("load mode must be replace or append")
        return {"cmd": "load", "files": files, "mode": mode}
    if kind == "play_index":
        idx = cmd.get("index")
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
            raise ValueError("play_index needs a non-negative integer")
        return {"cmd": "play_index", "index": idx}
    if kind == "quit":
        return {"cmd": "quit"}
    raise ValueError("unknown command: %s" % kind)


def encode_state(state: Dict[str, Any]) -> str:
    return STATE_PREFIX + json.dumps(state, separators=(",", ":"))


def decode_state(line: str) -> Optional[Dict[str, Any]]:
    """Parse an @state line from the player, or return None for any other output line."""
    if not line.startswith(STATE_PREFIX):
        return None
    try:
        data = json.loads(line[len(STATE_PREFIX) :])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
