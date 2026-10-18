# Troubleshooting and limits

## Calibrate / troubleshoot

**Head tracking moves the wrong way, or is rotated.** Run with `--debug` to confirm packets arrive
(`dk2 packets=...` should count up). Then try axis maps until looking left turns left, up looks up
and tilting your head tilts the image:

```
bluehour --axis-map "-x,y,-z" movie.mp4
bluehour --axis-map "x,z,-y"  movie.mp4
```

Each entry is one of `x`, `y`, `z` with an optional minus sign. Press **R** to recenter.

**No packets / "DK2 tracker unavailable".** Close anything else using the headset (Oculus runtime,
OpenHMD tools). On Linux check the udev rule above. You can force mouse mode with `--tracking mouse`.

**Image looks bent or too small/large.** Adjust with `,` `.` (distortion) and `;` `'` (FOV scale).
For flat movies set a comfortable size with `-` `=` and `9` `0`.

**Colour fringes at the edges.** Tune `--ca` (try 0.003 to 0.01) or set `--ca 0`.

**Video is slow or stutters.** Try `--hwdec auto` / `--hwdec no`. Keep very high resolution
(8K VR files) off; 4K is the practical ceiling for a decent PC, and the DK2 panel cannot show more
than about 1K per eye anyway.

**Picture on the wrong monitor / blank.** Use `--list-monitors`, then `--monitor N`.

## Known limitations

- Position tracking is crude (see section 6): it is not the official 6-DoF tracking.
- Lens distortion uses generic DK1/DK2-style coefficients, not your factory profile.
- No on-screen menu: mpv's own OSD (seek bar, volume) appears on the virtual screen in flat modes.
- Fisheye VR180 files are not supported, only equirectangular.
- Windows and Linux only (macOS drivers for the DK2 are not available).
