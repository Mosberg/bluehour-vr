"""Every setting of the player, described once. The command line, the GUI and the tests all read this table.

Standard library only: the GUI imports it without numpy, GLFW or mpv.
"""
import json
import os
import re
from dataclasses import dataclass

from .paths import config_dir

PROJ = ("flat", "curved", "vr180", "vr360")
STEREO = ("mono", "sbs", "ou")
POSITION = ("auto", "camera", "wii", "neck", "none")
ROTATE = ("none", "cw", "flip", "ccw")
TRACKING = ("auto", "dk2", "mouse")
WII = ("auto", "controller", "camera", "both", "off")


@dataclass(frozen=True)
class Field:
    name: str                 # the argparse destination, e.g. "screen_width"
    flag: str                 # the command-line flag, e.g. "--screen-width"
    kind: str                 # choice | float | int | bool | text | vec4
    default: object
    label: str
    group: str
    help: str = ""
    choices: tuple = ()
    min: float = None
    max: float = None
    step: float = None
    unit: str = ""
    live: bool = False        # can change while the player runs
    auto: bool = False        # empty / "auto" means "do not pass the flag"
    suggestions: tuple = ()   # for text fields: values worth offering

    def to_json(self):
        d = {k: getattr(self, k) for k in ("name", "flag", "kind", "default", "label", "group", "help", "unit",
                                           "live", "auto")}
        d.update(choices=list(self.choices), min=self.min, max=self.max, step=self.step,
                 suggestions=list(self.suggestions))
        return d


FIELDS = [
    # ---- layout (live) ----
    Field("proj", "--proj", "choice", "auto", "Screen type", "layout",
          "Flat or curved screen, or VR180 / VR360 video. Auto reads it from the file name.",
          ("auto",) + PROJ, live=True, auto=True),
    Field("stereo", "--stereo", "choice", "auto", "3D layout", "layout",
          "Mono, side-by-side or over-under. Auto reads it from the file name.",
          ("auto",) + STEREO, live=True, auto=True),
    Field("swap_eyes", "--swap-eyes", "bool", False, "Swap eyes", "layout",
          "Use if the 3D looks inside-out.", live=True),
    Field("rotate", "--rotate", "choice", "none", "Rotate output", "layout",
          "The DK2 panel is physically portrait. Turn the picture until it is upright.", ROTATE, live=True),
    # ---- screen and lens (live) ----
    Field("screen_width", "--screen-width", "float", 4.0, "Screen width", "image",
          "Width of the virtual screen (flat and curved).", min=0.5, max=40.0, step=0.1, unit="m", live=True),
    Field("distance", "--distance", "float", 3.0, "Screen distance", "image",
          "How far away the virtual screen is.", min=0.5, max=30.0, step=0.1, unit="m", live=True),
    Field("ipd", "--ipd", "float", 63.5, "IPD", "image",
          "Distance between your pupils. The DK2 default is 63.5 mm.", min=50.0, max=75.0, step=0.5,
          unit="mm", live=True),
    Field("fov_scale", "--fov-scale", "float", 0.9, "Field-of-view scale", "image",
          "Zoom the whole picture in or out.", min=0.4, max=1.6, step=0.01, live=True),
    Field("k", "--k", "vec4", [1.0, 0.22, 0.24, 0.0], "Lens distortion (k0 to k3)", "image",
          "Radial distortion coefficients. k1 is the one to adjust first.", min=-2.0, max=3.0, step=0.01,
          live=True),
    Field("ca", "--ca", "float", 0.005, "Colour fringing correction", "image",
          "Chromatic aberration correction. 0 turns it off.", min=0.0, max=0.05, step=0.001, live=True),
    # ---- display ----
    Field("monitor", "--monitor", "int", None, "Monitor", "display",
          "Which monitor to go fullscreen on. Auto picks a secondary 1920x1080 monitor.", min=0, max=16, auto=True),
    Field("windowed", "--windowed", "bool", False, "Preview window", "display",
          "Show a side-by-side window instead of going fullscreen. Works without a headset."),
    # ---- head tracking ----
    Field("tracking", "--tracking", "choice", "auto", "Head tracking", "tracking",
          "Auto uses the DK2 motion sensor and falls back to mouse look.", TRACKING),
    Field("axis_map", "--axis-map", "text", "x,y,z", "Sensor axis map", "tracking",
          "Remap sensor axes if looking left turns right, for example -x,y,-z.",
          suggestions=("x,y,z", "-x,y,-z", "x,z,-y", "-x,z,y")),
    Field("no_led_enable", "--no-led-enable", "bool", False, "Do not switch on the headset LEDs", "tracking",
          "Skip the report that lights the DK2 tracking LEDs."),
    # ---- position (leaning and moving) ----
    Field("position", "--position", "choice", "auto", "Position source", "position",
          "Where leaning and moving comes from. Auto tries the DK2 camera, then a Wii Remote, then the neck model.",
          POSITION, live=True),
    Field("move_scale", "--move-scale", "float", 1.0, "Movement scale", "position",
          "1.0 is real size. Raise it to exaggerate head movement.", min=0.0, max=5.0, step=0.1, live=True),
    Field("camera", "--camera", "int", None, "DK2 camera index", "position",
          "Auto finds a 752x480 camera.", min=0, max=9, auto=True),
    Field("cam_fov", "--cam-fov", "float", 74.0, "Camera field of view", "position",
          "Horizontal field of view of the camera.", min=20.0, max=140.0, step=1.0, unit="deg"),
    Field("cam_distance", "--cam-distance", "float", 1.0, "Camera distance", "position",
          "Real distance between camera and headset when you press recenter. Scales all movement.",
          min=0.3, max=3.0, step=0.05, unit="m"),
    Field("cam_threshold", "--cam-threshold", "int", 180, "LED brightness threshold", "position",
          "Lower it if no LEDs are found, raise it if lamps or windows add false blobs.", min=0, max=255, step=1),
    Field("cam_axis_map", "--cam-axis-map", "text", "x,y,z", "Camera axis map", "position",
          "Remap camera position axes, for example -x,y,z.", suggestions=("x,y,z", "-x,y,z", "x,-y,z", "x,y,-z")),
    # ---- Wii Remote ----
    Field("wii", "--wii", "choice", "auto", "Wii Remote use", "wii",
          "Auto: one remote is the controller, two are controller plus IR camera.", WII),
    Field("wii_swap", "--wii-swap", "bool", False, "Swap controller and camera remote", "wii",
          "Use the other remote as the controller."),
    Field("wii_ir_level", "--wii-ir-level", "int", 3, "IR sensitivity", "wii",
          "1 to 5. Raise it if the remote does not see the headset LEDs.", min=1, max=5, step=1),
    Field("wii_fov", "--wii-fov", "float", 45.0, "Wii camera field of view", "wii",
          "Adjust until 10 cm of leaning reads about 0.10.", min=10.0, max=120.0, step=1.0, unit="deg"),
    Field("wii_distance", "--wii-distance", "float", 1.0, "Wii camera distance", "wii",
          "Real distance between the remote and the headset when you press recenter.",
          min=0.3, max=3.0, step=0.05, unit="m"),
    Field("wii_axis_map", "--wii-axis-map", "text", "x,y,z", "Wii axis map", "wii",
          "Remap Wii position axes, for example x,-y,z.", suggestions=("x,y,z", "x,-y,z", "-x,y,z", "x,y,-z")),
    # ---- gamepad ----
    Field("no_gamepad", "--no-gamepad", "bool", False, "Ignore USB gamepads", "gamepad",
          "Turn off Xbox, PlayStation and adapter input."),
    Field("pad_file", "--pad-file", "text", "", "Mapping file", "gamepad",
          "Where learned controller mappings are stored. Empty uses the per-user folder.", auto=True),
    # ---- playback ----
    Field("volume", "--volume", "float", 80.0, "Volume", "playback", "", min=0.0, max=130.0, step=1.0,
          unit="%", live=True),
    Field("hwdec", "--hwdec", "text", "auto-safe", "Hardware decoding", "playback",
          "Try auto or no if video stutters or shows garbage.",
          suggestions=("auto-safe", "auto", "no", "d3d11va", "nvdec", "vaapi")),
    Field("audio_device", "--audio-device", "text", "", "Audio device", "playback",
          "An mpv audio device name. Empty uses the system default. List them with: mpv --audio-device=help",
          auto=True),
    Field("debug", "--debug", "bool", False, "Debug output", "playback", "Print tracker packet counts and more."),
]

BY_NAME = {f.name: f for f in FIELDS}
LIVE = {f.name for f in FIELDS if f.live}

# One-shot or interactive helpers that run instead of the player.
TOOLS = {
    "list_monitors": ("--list-monitors", "List monitors", "Shows every monitor the player can use."),
    "list_cameras": ("--list-cameras", "List cameras", "Finds the DK2 camera (752x480)."),
    "cam_test": ("--cam-test", "Camera test", "Preview window with the detected LEDs and x/y/z numbers."),
    "wii_test": ("--wii-test", "Wii Remote test", "Buttons, IR points and the computed position."),
    "pad_test": ("--pad-test", "Controller test", "Shows what every controller sends. Stop it when done."),
    "pad_config": ("--pad-config", "Teach a controller", "Press a button, then each control it asks for."),
    "doctor": ("--doctor", "Check setup", "Looks for Python packages, libmpv, the DK2, Wii Remotes and controllers."),
}

# Command-line options that are not settings: the GUI handles them separately.
NOT_SETTINGS = {"files", "help", "version", "control"}


def defaults():
    return {f.name: (list(f.default) if isinstance(f.default, list) else f.default) for f in FIELDS}


def coerce(name, value):
    """Validate and convert one value from JSON or a form. Raises ValueError with a readable message."""
    f = BY_NAME.get(name)
    if f is None:
        raise ValueError("unknown setting: %s" % name)
    if value is None or value == "":
        if f.auto or f.kind == "int" and f.default is None:
            return f.default
        if f.kind == "text":
            return f.default
        raise ValueError("%s needs a value" % f.label)
    if f.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError("%s must be true or false" % f.label)
    if f.kind == "choice":
        if value not in f.choices:
            raise ValueError("%s must be one of: %s" % (f.label, ", ".join(f.choices)))
        return value
    if f.kind in ("int", "float"):
        if isinstance(value, bool):
            raise ValueError("%s must be a number" % f.label)
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError("%s must be a number" % f.label) from None
        if num != num or num in (float("inf"), float("-inf")):
            raise ValueError("%s must be a finite number" % f.label)
        if f.min is not None and num < f.min or f.max is not None and num > f.max:
            raise ValueError("%s must be between %g and %g" % (f.label, f.min, f.max))
        return int(round(num)) if f.kind == "int" else num
    if f.kind == "vec4":
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError("%s needs four numbers" % f.label)
        out = []
        for v in value:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                raise ValueError("%s needs four numbers" % f.label)
            if v < f.min or v > f.max:
                raise ValueError("%s values must be between %g and %g" % (f.label, f.min, f.max))
            out.append(float(v))
        return out
    if f.kind == "text":
        if not isinstance(value, str) or "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("%s must be a single line of text" % f.label)
        text = value.strip()
        if f.name.endswith("axis_map"):
            parts = [p.strip() for p in text.split(",")]
            if len(parts) != 3 or any(not re.fullmatch(r"[+-]?[xyz]", p) for p in parts):
                raise ValueError("%s must look like x,y,z or -x,z,y" % f.label)
            return ",".join(parts)
        return text
    raise ValueError("unsupported kind: %s" % f.kind)


def clean(values):
    """Merge saved values over the defaults, dropping unknown keys and invalid values."""
    out = defaults()
    for name, value in (values or {}).items():
        if name in BY_NAME:
            try:
                out[name] = coerce(name, value)
            except ValueError:
                pass
    return out


def to_argv(values, files=(), control=True):
    """Command-line arguments for a settings dict. Values that equal the default are left out.

    Every value is passed as --flag=value so text can never be mistaken for a flag, and files follow a `--`.
    """
    v = clean(values)
    argv = []
    for f in FIELDS:
        value = v[f.name]
        if f.auto and (value is None or value == "" or value == "auto"):
            continue
        if value == f.default:
            continue
        if f.kind == "bool":
            if value:
                argv.append(f.flag)
        elif f.kind == "vec4":
            argv.append(f.flag)
            argv.extend(repr(float(x)) for x in value)
        elif f.kind == "float":
            argv.append("%s=%r" % (f.flag, float(value)))
        else:
            argv.append("%s=%s" % (f.flag, value))
    if control:
        argv.append("--control")
    if files:
        argv.append("--")
        argv.extend(str(p) for p in files)
    return argv


def schema():
    return {"fields": [f.to_json() for f in FIELDS],
            "tools": [{"id": k, "flag": v[0], "label": v[1], "help": v[2]} for k, v in TOOLS.items()]}


# ---------------------------------------------------------------------------------------------
# Saved state for the GUI: settings, playlist and presets live in one JSON file.
# ---------------------------------------------------------------------------------------------

def state_path():
    return os.path.join(config_dir(), "gui.json")


def load_state(path=None):
    try:
        with open(path or state_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    playlist = data.get("playlist")
    presets = data.get("presets")
    return {
        "settings": clean(data.get("settings")),
        "playlist": [p for p in playlist if isinstance(p, str)] if isinstance(playlist, list) else [],
        "presets": {str(k): clean(v) for k, v in presets.items()} if isinstance(presets, dict) else {},
    }


def save_state(state, path=None):
    path = path or state_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
