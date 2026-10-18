# Wii Remote

Two independent jobs, both optional. By default (`--wii auto`) the player looks for paired Wii Remotes
at start-up: **one remote = controller**, **two or more = first is the controller, second is an IR
camera** for position tracking. Force a role with `--wii controller|camera|both|off`, and swap which
remote does what with `--wii-swap`.

Needs `hidapi` (installed with Bluehour). Supports the original Wii Remote and the Wii Remote Plus.
It does not use the accelerometer, MotionPlus or extensions.

## Pairing

The remote must be paired with your PC as a Bluetooth HID device first. Both vendor IDs (RVL-CNT-01
and the newer -TR / Plus) are recognised.

- **Linux:** `bluetoothctl` → `scan on` → press the red SYNC button (or 1+2) → `pair` / `connect`
  the "Nintendo RVL-CNT-01". Use a udev rule so you can open it without root:

  ```
  # /etc/udev/rules.d/84-wiimote.rules
  KERNEL=="hidraw*", ATTRS{idVendor}=="057e", MODE="0666"
  ```

  If buttons or IR behave oddly, the kernel's `hid_wiimote` driver may be fighting for the device:
  try `sudo modprobe -r hid_wiimote` and pair again.
- **Windows:** Settings → Bluetooth → Add device → press the red SYNC button (or 1+2) → pick
  "Nintendo RVL-CNT-01". If asked for a PIN, choose the option to connect without one. This is the
  fragile part: some Bluetooth adapters/stacks refuse to keep the pairing, and the remote often has to
  be re-paired (or woken with 1+2) when it falls asleep. If it will not stay paired, the Wii Remote
  features simply do not start and nothing else is affected.

Check it works with `python -m bluehour.wiimote` (press buttons; add `--ir` to see IR points) or
`bluehour --wii-test`.
## As a remote control

| Wii Remote | Action |
|---|---|
| A | Pause / play |
| B | Recenter view and position (the remote buzzes briefly) |
| D-pad left / right | Seek 10 s back / forward (hold to repeat) |
| D-pad up / down | Volume up / down (hold to repeat) |
| + / - | Seek 60 s forward / back |
| 1 | Cycle mono / SBS / OU |
| 2 | Cycle flat / curved / VR180 / VR360 |
| Home | Cycle position source |

LED 1 lights while the controller is connected.

## As a position camera (needs a second remote)

The Wii Remote's IR camera can watch the headset's LEDs, a bit like the DK2 camera does. Useful if the
DK2 camera is not usable on your PC.

1. Stand the second remote on top of your monitor, **A button facing up, front (IR window) pointing at
   you**, about 1 m away from your seated head position. LED 4 lights on this remote.
2. Run `bluehour --wii-test`. It prints the IR points the remote sees and the computed x/y/z.
   Sit at your viewing position, press A on the *controller* remote to recenter, then lean 10 cm right:
   x should be about +0.10; up: y positive; toward the remote: z negative.
3. Fix directions with `--wii-axis-map` (for example `x,-y,z`), distances with `--wii-distance`, and the
   camera's field of view with `--wii-fov` (default 45°, an approximation: adjust until 10 cm of leaning
   reads about 0.10).
4. Run the player normally; with `--position auto` it is used whenever the DK2 camera is not tracking.
   Press `V` to force it (`wii`).

Limits to expect:

- The remote only reports its **four brightest points**, and the DK2's ~40 LEDs merge into a few blobs,
  so the result is noisier than the DK2 camera and can jump when blobs change identity.
- The DK2's LEDs pulse in time with the DK2 camera's exposure; a Wii Remote watching them may see them
  flicker or look dim. Raise sensitivity with `--wii-ir-level 4` or `5` (1-5, default 3).
- Sunlight, lamps and candles are IR sources too and will confuse it.
- Wii Remotes switch themselves off after a while without button presses; a remote that is only a
  camera may drop out. If that happens, wake it with 1+2 (the player reconnects on its own when it can).
- Whether the DK2's LED wavelength suits the Wii Remote camera is not verified; it should, but test
  with `--wii-test` first.
