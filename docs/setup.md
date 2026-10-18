# Set up

## Install

Python 3.9+.

```
pip install git+https://github.com/Mosberg/bluehour-vr.git
```

Or, from a clone of the repository: `pip install -e .` (a PyPI release is planned; see the [changelog](../CHANGELOG.md)).

**libmpv** is also needed:

- **Windows:** download a libmpv build (`libmpv-2.dll` / `mpv-2.dll`, e.g. from the mpv-winbuild or
  shinchiro builds) and put the DLL in the folder you run Bluehour from (or point `BLUEHOUR_LIBMPV_DIR` at its folder).
- **Linux:** `sudo apt install libmpv2` (or `libmpv1` on older distros). Optionally `hidapi` needs
  `libhidapi-hidraw0`, and you need a udev rule so you can read the DK2 without root:

  ```
  # /etc/udev/rules.d/83-dk2.rules
  KERNEL=="hidraw*", ATTRS{idVendor}=="2833", MODE="0666"
  ```

## Set up the DK2 display

1. Plug in the DK2: HDMI to the **graphics card** (not the motherboard) and USB to the PC. Power it on.
2. Make it an extended desktop monitor (**not** a duplicate of your main screen).
3. Set it to **1920x1080 @ 75 Hz**.
4. The DK2 panel is physically portrait. If Windows/Linux shows it as 1080x1920 or the image is on its
   side, either rotate it in display settings, or leave it and press **F** in the player to cycle the
   output rotation until the picture is upright.

Check what the player sees with `bluehour --list-monitors`.
