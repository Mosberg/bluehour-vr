# Set up

## Install

Python 3.9+.

```
pip install git+https://github.com/Mosberg/bluehour-vr.git
```

Or, from a clone of the repository: `pip install -e .` (a PyPI release is planned; see the [changelog](../CHANGELOG.md)).

**libmpv** is also needed:

- **Windows:** Bluehour needs one file, `libmpv-2.dll`, in a 64-bit build (use 64-bit Python).
  1. Go to <https://github.com/shinchiro/mpv-winbuild-cmake/releases> and download the newest
     `mpv-dev-x86_64-...7z` file (not the `v3` or `i686` ones). Unpack it with 7-Zip.
  2. Copy `libmpv-2.dll` (sometimes named `mpv-2.dll`) out of it into a folder of your own, for example `C:\bluehour`.
  3. Tell Bluehour where it is. In a terminal run `setx BLUEHOUR_LIBMPV_DIR "C:\bluehour"`, then close the terminal and open a new one.
  4. Check with `bluehour --doctor`. It says whether libmpv was found.

  Instead of step 3 you can put the DLL in the folder the terminal is in when you run `bluehour`.
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
