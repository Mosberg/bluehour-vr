"""A stand-in for `python -m bluehour` used by the GUI tests: speaks the same stdin/stdout protocol."""
import json
import sys
import threading
import time

args = sys.argv[1:]
if "--doctor" in args:
    print("[ ok ] Python: fake")
    print("@doctor " + json.dumps([{"name": "Python", "status": "ok", "detail": "fake", "hint": ""}]))
    sys.exit(0)
if "--list-monitors" in args:
    print("0: Main  2560x1440 @ 144 Hz  (primary)")
    print("1: DK2  1920x1080 @ 75 Hz")
    sys.exit(0)
if "--list-cameras" in args:
    print("camera 0: 752x480   <- looks like the DK2 camera")
    sys.exit(0)
if "--pad-test" in args:
    print("Controller test.", flush=True)
    sys.stdin.read()
    sys.exit(0)

print("fake player started: " + " ".join(args), flush=True)
st = {"pause": False, "mute": False, "time": 0.0, "duration": 100.0, "volume": 80.0, "file": "x.mp4", "index": 0,
      "playlist": ["x.mp4"], "proj": "flat", "stereo": "mono", "swap_eyes": False, "rotate": "none",
      "screen_width": 4.0, "distance": 3.0, "ipd": 63.5, "fov_scale": 0.9, "k": [1, .22, .24, 0], "ca": .005,
      "position": "auto", "position_now": "neck", "move_scale": 1.0, "head_tracker": "mouse",
      "wii_controller": False, "wii_camera": False, "camera": False, "gamepads": 0, "log": []}
running = True


def reader():
    global running
    for line in sys.stdin:
        cmd = json.loads(line)
        st["log"].append(cmd)
        if cmd["cmd"] == "quit":
            running = False
            return
        if cmd["cmd"] == "set":
            st[cmd["name"]] = cmd["value"]
        if cmd["cmd"] == "action" and cmd["name"] == "pause":
            st["pause"] = not st["pause"]
        if cmd["cmd"] == "seek":
            st["time"] = cmd["value"]
    running = False


threading.Thread(target=reader, daemon=True).start()
while running:
    print("@state " + json.dumps(st), flush=True)
    time.sleep(0.05)
