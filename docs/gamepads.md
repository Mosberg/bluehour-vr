# USB gamepads and the raphnet adapter

Any controller that shows up in Windows as a game controller works as a remote. The player polls them
through GLFW and needs nothing extra to install. Plug in before or during playback; hot-plugging works.
Disable with `--no-gamepad`.

## Default mapping (controllers GLFW recognises as gamepads)

| Control | Action |
|---|---|
| A / Cross | Pause / play |
| B / Circle | Recenter view |
| X / Square | Cycle mono / SBS / OU |
| Y / Triangle | Cycle FLAT / CURVED / VR180 / VR360 |
| D-pad left / right | Seek 10 s (hold to repeat) |
| D-pad up / down | Volume (hold to repeat) |
| LB / RB | Seek 60 s back / forward |
| Back / Select | Mute |
| Start | Cycle position source |

## Per controller

- **Xbox One controller (USB):** works with Windows' built-in driver and the default mapping.
- **PS3 controller (USB):** Windows does not give it a proper gamepad driver. Install a driver such as
  DsHidMini or SCP Driver Package so it appears as an Xbox-style pad, then the default mapping applies.
  If it already shows up as a plain joystick, teach it with `--pad-config` instead.
- **raphnet Classic controller adapter (Classic, Classic Pro, SNES/NES Classic, Nunchuk, guitars):**
  it is a standard USB joystick, so no driver is needed, but GLFW has no built-in layout for it. Run
  `bluehour --pad-config` once per controller type you plug in.

## Teaching a controller

1. `bluehour --pad-config`
2. Press any button on the controller to pick it.
3. For each action it asks for, press the control you want (wait about 12 s to skip an action).
   Buttons, D-pads (hats), and stick or trigger directions can all be used.
4. The result is saved per controller name in `gamepad.json` (Windows: `%APPDATA%\bluehour`, Linux: `~/.config/bluehour`) or the file given by
   `--pad-file`. Delete the entry or the file to start over.

The raphnet adapter reports a different name for each connected accessory type in some firmware
setups. If a Nunchuk or guitar is not picked up after switching accessories, run `--pad-config` again
with that accessory. The adapter manager tool can set the D-pad to act as buttons or as axes; both work.

## Checking what a controller sends

`bluehour --pad-test` prints every button, hat and axis direction as you press it, and the
action your mapping triggers. Use it to confirm a controller is seen at all.
