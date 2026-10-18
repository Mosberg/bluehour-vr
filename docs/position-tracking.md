# Leaning and moving

The player has two position sources. `V` cycles them, `--position auto|camera|wii|neck|none` sets the start
mode. `auto` (default) uses the DK2 camera while it can see the headset LEDs, then a Wii Remote IR camera (see [Wii Remote](wii-remote.md)) if one is set up, and otherwise the neck model.

**Neck model (always available).** Treats your head as pivoting on your neck, so nodding, tilting and
turning move your eyes a few centimetres, which gives the parallax cue you get from the DK1-style
"head and neck" model. It cannot see you lean your torso or step sideways.

**DK2 camera (experimental).** Real leaning and moving, using the camera that came with the DK2:

- Left/right and up/down come from where the cluster of IR LEDs appears in the camera image.
- Forward/back comes from how tall the cluster looks (it is roughly constant when you turn your head).
- It does **not** identify individual LEDs, so this is a coarse 3-axis estimate, not the official
  sub-millimetre tracking. Expect some jitter and a little drift when you roll your head a lot.
  Rotation always comes from the IMU.

## Setup

1. `pip install opencv-python` (installed with Bluehour).
2. Connect the camera to a **USB 3.0** port and plug in the sync cable between the camera and the
   headset, exactly as for the official software. Place the camera at about eye height, facing you,
   about 1 m away.
3. Run `bluehour --list-cameras`. The DK2 camera should show up as **752x480**, marked
   "looks like the DK2 camera". If it does not appear, the camera is not exposed as a normal webcam
   on your system (see below).
4. Run `bluehour --cam-test` (add `--camera N` if needed). A window shows the detected LEDs as
   green circles and prints x/y/z in metres. Sit at your normal viewing position and press **R**. Then
   lean right 10 cm: x should read about +0.10; lean up: y positive; move toward the camera: z negative.
5. Fix anything that is the wrong way round with `--cam-axis-map` (for example `-x,y,z`).
6. Start the player normally. Press **R** at your normal seating position to recenter both the view and
   the camera position.

## Tuning

| Option | Use |
|---|---|
| `--cam-distance 1.2` | Real distance (metres) between camera and headset when you press R. Scales all movement. |
| `--cam-fov 74` | Camera horizontal field of view in degrees. |
| `--cam-threshold 180` | Lower it if no LEDs are found, raise it if lamps or windows add false blobs. |
| `--move-scale 1.0` | Exaggerate (>1) or reduce (<1) head movement. |
| `--no-led-enable` | Do not send the "LEDs on" report to the headset (see below). |

## If the camera does not work

- **No LEDs found / "no LEDs found" in the test window.** The player sends a "tracking on" report to the
  headset to light the LEDs. I wrote that report from memory of the Oculus HID documentation and could not
  verify it on hardware. Try the official runtime once to light the LEDs, or look at the camera image in
  another app: IR LEDs appear as bright dots on the dark image. Also avoid sunlight and bright lamps in
  the camera's view.
- **Camera not listed.** On Linux the DK2 camera normally appears as a V4L2 device (`/dev/video*`). On
  Windows it may only be exposed through the Oculus drivers. In that case the neck model still works
  and the camera is simply skipped.
- **Image flickers or LEDs blink in and out.** The camera normally runs in sync with the headset
  through the sync cable. Check the cable.
- Movement feels too large or too small: adjust `--cam-distance` or `--move-scale`.
