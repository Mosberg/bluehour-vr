# Use

## Run

```
bluehour movie.mp4
bluehour movie_sbs.mp4                  # 3D side-by-side (guessed from the name)
bluehour --proj vr180 --stereo sbs clip.mp4
bluehour --proj vr360 --stereo ou tour.mp4
bluehour                                # opens a file chooser
bluehour --windowed movie.mp4           # side-by-side preview window, no headset needed
```

The player goes fullscreen on a secondary 1920x1080 monitor automatically. If that fails, use
`--monitor N`. Without a headset it opens a preview window and uses mouse look.

File-name hints: `360`, `180`, `sbs`, `lr`, `ou`, `tb`, `3d`, `stereo`.

### Controls

| Key | Action |
|---|---|
| Space | Pause / play |
| Left / Right | Seek 10 s |
| PgUp / PgDn | Seek 60 s |
| Up / Down | Volume |
| M | Mute |
| N / P | Next / previous file |
| T / A | Cycle subtitles / audio track |
| R | Recenter view |
| 1 / 2 / 3 / 4 | Flat / curved / VR180 / VR360 |
| S | Cycle mono / SBS / OU |
| X | Swap eyes |
| - / = | Screen size |
| 9 / 0 | Screen distance |
| [ / ] | IPD (1 mm steps; DK2 default is 63.5) |
| ; / ' | Field-of-view scale |
| , / . | Lens distortion strength |
| F | Rotate output (portrait / flipped DK2 display) |
| V | Cycle position source: auto / camera / wii / neck / none |
| H | Print help |
| Esc / Q | Quit |

The status line printed after each change shows the current values, so you can copy good ones into
command-line flags (`--screen-width`, `--distance`, `--ipd`, `--fov-scale`, `--k`).

Half-SBS / half-OU movies (squeezed to 1920x1080) and full SBS / OU files are told apart by aspect
ratio automatically.
