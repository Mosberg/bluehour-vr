<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-dark.svg">
    <img src="assets/brand/logo.svg" alt="Bluehour" height="96">
  </picture>

  <p><strong>A VR media player for the Oculus Rift DK2.<br>No Oculus runtime, SteamVR or OpenXR needed.</strong></p>

  <p>
    <a href="https://github.com/Mosberg/bluehour-vr/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Mosberg/bluehour-vr/actions/workflows/ci.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-2E3F95"></a>
    <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-2E3F95">
    <img alt="Windows and Linux" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-2E3F95">
    <a href="https://mosberg.github.io/bluehour-vr/"><img alt="Docs" src="https://img.shields.io/badge/docs-mosberg.github.io-F6A85E"></a>
  </p>
</div>

The Oculus Rift DK2 has had no official support for years, and the current Oculus PC software does not
support it. Bluehour talks to the headset directly. The DK2 is used as an ordinary extra monitor for
video, and its motion sensor is read over USB for head tracking. You get a private cinema from a headset
that would otherwise sit in a drawer.

> [!IMPORTANT]
> **Status: alpha, not yet verified on real hardware.** The code was written without a DK2 or a Wii Remote
> attached. The maths, the sensor decoder, the camera tracker (on synthetic frames), the Wii Remote protocol
> (against a fake remote) and the gamepad logic are covered by automated tests. Lens values, axis
> directions, the USB packet layout and the camera and LED behaviour may need tuning on your headset.
> The [troubleshooting guide](docs/troubleshooting.md) explains how, and the
> [hardware test checklist](docs/hardware-testing.md) is how you can help close the gap.

## Features

- **Plays almost anything.** Decoding, audio and subtitles come from libmpv, including URLs when yt-dlp is installed.
- **Flat, curved, VR180 and VR360 layouts**, with mono, side-by-side and over-under 3D plus eye swap. The layout is guessed from the file name.
- **Lens distortion and chromatic aberration correction** for the DK2 lenses, tunable live.
- **Head rotation** from the DK2 motion sensor over USB, with mouse look as the fallback.
- **Leaning and moving** from the DK2 IR camera or a Wii Remote's IR camera, with a neck-model fallback. Position applies to flat and curved screens only, as VR video has no depth.
- **Remote control** from the keyboard, a Wii Remote, or any USB gamepad: Xbox One, PS3, or a raphnet adapter for Classic controllers, Nunchuks and guitars.

## Quick start

You need Python 3.9 or newer and libmpv. On Windows, put `libmpv-2.dll` in the folder you run Bluehour from.
On Debian or Ubuntu, `sudo apt install libmpv2`.

```bash
pip install git+https://github.com/Mosberg/bluehour-vr.git
bluehour --list-monitors          # find the DK2
bluehour movie.mp4                # flat movie
bluehour movie_sbs.mp4            # 3D, guessed from the name
bluehour --proj vr180 --stereo sbs clip.mp4
bluehour --windowed movie.mp4     # preview window, no headset needed
```

Set the DK2 up as an extended monitor at 1920x1080, 75 Hz first. The [setup guide](docs/setup.md) covers it.

## Documentation

| Guide                                                 | What it covers                                        |
| ----------------------------------------------------- | ----------------------------------------------------- |
| [Set up](docs/setup.md)                               | Install, libmpv, the DK2 display, Linux udev rules    |
| [Use](docs/usage.md)                                  | Commands, layouts, the full keyboard table            |
| [Troubleshooting and limits](docs/troubleshooting.md) | Tracking direction, distortion, stutter, known limits |
| [Leaning and moving](docs/position-tracking.md)       | DK2 camera and neck model                             |
| [Wii Remote](docs/wii-remote.md)                      | Remote control and IR camera, pairing                 |
| [USB gamepads](docs/gamepads.md)                      | Xbox One, PS3, raphnet adapter, learn mode            |
| [Architecture](docs/architecture.md)                  | How the pieces fit, for contributors                  |
| [Hardware test checklist](docs/hardware-testing.md)   | Report what works on your DK2                         |

The same guides are published at **<https://mosberg.github.io/bluehour-vr/>**.

## Project layout

```text
src/bluehour/     the package: player, tracking, shaders, quaternion maths, Wii Remote, gamepads
tests/            unit tests (standard library unittest, no hardware needed)
docs/             guides and the GitHub Pages site
assets/brand/     logo, icon and social preview
.github/          CI, Pages deploy, release workflow, issue and PR templates
```

## Development

```bash
git clone https://github.com/Mosberg/bluehour-vr.git
cd bluehour-vr
pip install -e ".[dev,camera]"
python -m unittest discover -s tests -t .
ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and hardware results are welcome: the
[issue templates](https://github.com/Mosberg/bluehour-vr/issues/new/choose) ask for the details that matter.

## Roadmap

- Verify and tune on real DK2 hardware, then drop the alpha label.
- Per-headset lens profile instead of generic coefficients.
- Fisheye VR180 input.
- PyPI release and a Windows bundle with libmpv included.

## Acknowledgements

Built on [mpv](https://mpv.io/) / libmpv, [GLFW](https://www.glfw.org/), [hidapi](https://github.com/libusb/hidapi),
[NumPy](https://numpy.org/) and [OpenCV](https://opencv.org/). The sensor packet decoding is based on publicly
available documentation of the DK2 HID protocol.

Bluehour is an independent project. It is not affiliated with or endorsed by Meta, Oculus, Nintendo, Microsoft,
Sony or raphnet. Oculus Rift, Wii, Xbox and PlayStation are trademarks of their respective owners.

## License

[MIT](LICENSE) © 2026 Rasmus Toftegård Mosberg
