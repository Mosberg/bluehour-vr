# Architecture

A short tour for contributors. Everything lives in `src/bluehour/`.

| Module | Job |
|---|---|
| `player.py` | Window, mpv, the render loop, keyboard handling, command line (`bluehour` entry point) |
| `shaders.py` | GLSL for the video quad, the eye renderer (projections, stereo, distortion) and the present pass |
| `tracking.py` | Head and position trackers: DK2 IMU, DK2 camera, Wii Remote IR, mouse, plus the camera and Wii test modes |
| `quat.py` | Quaternion and vector helpers shared by trackers and renderer |
| `wiimote.py` | Wii Remote driver over HID: buttons, IR, LEDs, rumble |
| `gamepad.py` | USB gamepads through GLFW: default mapping, learn mode, test mode |

## Frame path

1. **libmpv** decodes the video and renders into an OpenGL texture through its render API.
2. The **eye pass** draws each eye into an offscreen framebuffer. A fullscreen triangle runs a fragment shader that
   casts a ray per pixel through the chosen projection (flat plane, cylinder, equirectangular 180 or 360),
   picks the right half of the frame for the chosen 3D layout, and applies radial lens distortion with a small
   per-channel scale for chromatic aberration.
3. The **present pass** copies the result to the DK2 window and rotates it 0, 90, 180 or 270 degrees, because the DK2
   panel is natively portrait.

## Tracking

- `DK2Tracker` reads the headset's sensor reports over USB HID on a background thread, unpacks the 21-bit samples,
  integrates the gyro and corrects tilt drift with the accelerometer. Output is an orientation quaternion.
- Position comes from one of three sources, chosen by `--position` or the `V` key: the DK2 camera (`CameraTracker`),
  a Wii Remote IR camera (`WiiPosition`), or the neck model. In `auto` mode the first source that currently has a
  fix is used, in that order, falling back to the neck model.
- Position is added in the eye shader for flat and curved screens only. Video in VR180 and VR360 has no depth.

## Input

Keyboard, Wii Remote and gamepad all end up as the same key handler in `player.py`: the Wii Remote and gamepad
code turn presses into action names, and the player maps those to the key presses it would get from the keyboard.
One code path means one set of behaviour to test.

## Testing

Pure logic is unit-tested without hardware: quaternion maths, sensor unpacking, the One Euro filter, layout
guessing, Wii Remote report parsing with a fake device, and the gamepad mapping with a fake backend. Code that needs a
window, a GPU or a device (shaders, render loop, real HID I/O) cannot run in CI and is covered by the
[hardware test checklist](hardware-testing.md).
