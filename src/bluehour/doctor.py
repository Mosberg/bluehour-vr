"""`bluehour --doctor`: checks everything the player needs and says what to fix.

Prints readable lines, then one machine-readable `@doctor {...}` line that the GUI shows as a checklist.
"""

from __future__ import annotations

import importlib
import json
import sys

from .paths import prepare_library_path

DK2_VID, DK2_PID = 0x2833, 0x0021


def _check(checks, name, status, detail, hint=""):
    checks.append({"name": name, "status": status, "detail": detail, "hint": hint})


def _import(checks, module, label, required, hint):
    try:
        mod = importlib.import_module(module)
    except (
        Exception
    ) as exc:  # noqa: BLE001 - any import problem is a finding, not a crash
        _check(
            checks,
            label,
            "fail" if required else "warn",
            "%s: %s" % (type(exc).__name__, exc),
            hint(exc) if callable(hint) else hint,
        )
        return None
    _check(
        checks,
        label,
        "ok",
        "found" + (" " + str(mod.__version__) if hasattr(mod, "__version__") else ""),
    )
    return mod


def _mpv_hint(exc):
    if isinstance(exc, ImportError):
        return "pip install python-mpv"
    return (
        "python-mpv is installed but libmpv itself was not found. Download libmpv-2.dll (Windows) or install "
        "libmpv2 (Linux). Put the DLL in a folder and set BLUEHOUR_LIBMPV_DIR to it. See the setup guide."
    )


def collect():
    prepare_library_path()
    checks = []
    ver = "%d.%d.%d" % sys.version_info[:3]
    _check(
        checks,
        "Python",
        "ok" if sys.version_info >= (3, 9) else "fail",
        ver,
        "Bluehour needs Python 3.9 or newer.",
    )
    _import(checks, "numpy", "numpy", True, "pip install numpy")
    glfw = _import(
        checks, "glfw", "GLFW (window and controllers)", True, "pip install glfw"
    )
    _import(checks, "OpenGL", "PyOpenGL", True, "pip install PyOpenGL")
    _import(checks, "mpv", "libmpv (video decoding)", True, _mpv_hint)
    hid = _import(
        checks, "hid", "hidapi (headset sensor, Wii Remote)", True, "pip install hidapi"
    )
    _import(
        checks,
        "cv2",
        "OpenCV (DK2 camera tracking)",
        False,
        'Optional. pip install "bluehour-vr[camera]"',
    )

    if hid is not None:
        try:
            dk2 = hid.enumerate(DK2_VID, DK2_PID)
            _check(
                checks,
                "DK2 headset (USB)",
                "ok" if dk2 else "warn",
                "%d found" % len(dk2) if dk2 else "not found",
                (
                    ""
                    if dk2
                    else "Plug the DK2 USB cable in and power the headset. Mouse look is used meanwhile."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _check(checks, "DK2 headset (USB)", "warn", str(exc), "")
        try:
            from .wiimote import Wiimote

            n = len(Wiimote.find())
            _check(
                checks,
                "Wii Remotes (paired)",
                "ok" if n else "warn",
                "%d found" % n,
                (
                    ""
                    if n
                    else "Optional. Needs a Bluetooth adapter and a paired remote. See the Wii Remote guide."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _check(checks, "Wii Remotes (paired)", "warn", str(exc), "")

    if glfw is not None:
        try:
            if glfw.init():
                mons = glfw.get_monitors()
                primary = glfw.get_primary_monitor()
                dk2 = 0
                for m in mons:
                    vm = glfw.get_video_mode(m)
                    if m != primary and {vm.size.width, vm.size.height} == {1920, 1080}:
                        dk2 += 1
                _check(
                    checks,
                    "Monitors",
                    "ok" if dk2 else "warn",
                    "%d found, %d look like a DK2" % (len(mons), dk2),
                    (
                        ""
                        if dk2
                        else "Make the DK2 an extended desktop monitor at 1920x1080, 75 Hz. "
                        "The preview window works without it."
                    ),
                )
                pads = [
                    j
                    for j in range(glfw.JOYSTICK_1, glfw.JOYSTICK_LAST + 1)
                    if glfw.joystick_present(j)
                ]
                _check(
                    checks,
                    "USB controllers",
                    "ok" if pads else "warn",
                    "%d found" % len(pads),
                    (
                        ""
                        if pads
                        else "Optional. Plug in an Xbox, PlayStation or adapter controller."
                    ),
                )
                glfw.terminate()
            else:
                _check(
                    checks, "Monitors", "warn", "GLFW could not start (no display?)", ""
                )
        except Exception as exc:  # noqa: BLE001
            _check(checks, "Monitors", "warn", str(exc), "")
    return checks


def run():
    checks = collect()
    marks = {"ok": " ok ", "warn": "warn", "fail": "FAIL"}
    for c in checks:
        print("[%s] %s: %s" % (marks[c["status"]], c["name"], c["detail"]))
        if c["hint"] and c["status"] != "ok":
            print("       -> %s" % c["hint"])
    failed = [c for c in checks if c["status"] == "fail"]
    print(
        "\n%s"
        % (
            "Everything required is in place."
            if not failed
            else "%d required item(s) need attention." % len(failed)
        )
    )
    print("@doctor " + json.dumps(checks))
    return 1 if failed else 0
