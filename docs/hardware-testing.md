# Hardware test checklist

Bluehour is alpha because it has not been verified on real hardware. If you have a DK2, running through this list
and opening a **Hardware report** issue is the most useful thing you can do. Skip steps for devices you do not have.

Run each command with `--debug` and keep the output if something fails.

## 1. Display

- [ ] `bluehour --list-monitors` shows the DK2 as a 1920x1080 (or 1080x1920) monitor.
- [ ] `bluehour movie.mp4` goes fullscreen on the DK2. Note if you needed `--monitor N` or `--rotate`.
- [ ] The picture is upright after pressing **F** zero to three times.
- [ ] Straight lines look straight at the centre of each lens. Note any `--k` change that helped.

## 2. Head tracking

- [ ] `--debug` prints `dk2 packets=...` and the number rises.
- [ ] Looking left turns the view left, looking up looks up, tilting tilts. Note the `--axis-map` you needed.
- [ ] The view does not drift noticeably over five minutes. Press **R** to recenter.

## 3. Position tracking

- [ ] `bluehour --list-cameras` lists a 752x480 camera marked as the DK2 camera.
- [ ] `bluehour --cam-test` shows green circles on the LEDs. Leaning 10 cm moves x or y by about 0.10.
- [ ] Note whether the headset LEDs were already lit, or needed the official software once.

## 4. Wii Remote

- [ ] `python -m bluehour.wiimote` shows button presses. Add `--ir` to see IR points.
- [ ] Note the Bluetooth adapter and how pairing went on your OS.

## 5. Gamepad

- [ ] `bluehour --pad-test` lists your controller and prints its presses.
- [ ] The default mapping works, or `bluehour --pad-config` produced a working mapping.

## Reporting

Open a [Hardware report](https://github.com/Mosberg/bluehour-vr/issues/new?template=hardware_report.yml) with the
results, the flags you needed, your OS, GPU and the version from `bluehour --version`.
