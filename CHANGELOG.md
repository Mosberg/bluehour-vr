# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-18

First public version. Alpha: not yet verified on real DK2 hardware.

### Added
- Media playback through libmpv with flat, curved, VR180 and VR360 layouts and mono, SBS and OU 3D.
- DK2 lens distortion and chromatic aberration shader, live tuning of size, distance, IPD and field of view.
- Head rotation from the DK2 IMU over USB HID, with mouse look fallback.
- Position tracking: DK2 IR camera, Wii Remote IR camera, neck model, with an automatic fallback chain.
- Wii Remote driver (buttons, IR, LEDs, rumble) as a remote control and as a position camera.
- USB gamepad support through GLFW with a default Xbox-style mapping, a learn mode (`--pad-config`) and a test mode (`--pad-test`).
- Unit tests, CI for Windows and Linux, GitHub Pages documentation.

[Unreleased]: https://github.com/Mosberg/bluehour-vr/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Mosberg/bluehour-vr/releases/tag/v0.1.0
