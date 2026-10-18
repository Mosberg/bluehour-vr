# Control panel

The control panel is a window where every Bluehour option can be changed, with no commands to remember.

## Start it

```
bluehour-gui
```

It opens a window (an app window in Chrome or Edge if you have one, otherwise your browser). The address in the
terminal contains a private key, so only this computer and this run can use it. Closing the terminal or pressing
**Quit** stops it. Use `bluehour-gui --no-browser` to print the address without opening anything.

## Tabs

| Tab | What it does |
|---|---|
| Play | Playlist (add videos with the file picker or a web address, reorder, remove), presets, setup summary |
| Image | Screen type, 3D layout, swap eyes, screen size and distance, IPD, field of view, lens distortion, colour fringing |
| Display | Which monitor is the DK2, windowed preview, output rotation |
| Tracking | Head tracking source, axis map, position source, DK2 camera settings and tests |
| Controllers | Wii Remote and USB gamepad options, tests, teaching, and the mapping editor |
| Playback | Volume, hardware decoding, audio device, debug output |
| Tools | Setup check and the helper tools (list monitors, camera test, Wii test, controller tests) |
| Output | Everything the player and helpers print |
| Help | Keyboard, Wii Remote and gamepad controls |

## While a video plays

- The bar at the bottom controls playback: previous, seek, pause, next, volume, mute, recenter, subtitles, audio track.
- Settings marked **live** change in the headset at once. The sliders also follow changes you make with the keyboard,
  a Wii Remote or a gamepad. **Keep these values as my settings** saves what is in the headset.
- Other settings apply the next time the player starts. A banner lists them with a **Restart player** button.

## Settings and presets

Settings are saved automatically in a per-user folder (`%APPDATA%\bluehour` on Windows, `~/.config/bluehour` on Linux).
A preset stores all settings under a name. Every option is also available on the command line, and the panel shows
the same defaults.
