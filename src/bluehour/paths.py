"""Per-user folders and library lookup. Standard library only, so the GUI can import it without numpy or GLFW."""
import os
import sys


def config_dir():
    """%APPDATA%\\bluehour on Windows, $XDG_CONFIG_HOME/bluehour (or ~/.config/bluehour) elsewhere."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "bluehour")


def prepare_library_path():
    """Let libmpv-2.dll / mpv-2.dll be found in $BLUEHOUR_LIBMPV_DIR, the current folder or the package folder."""
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in filter(None, (os.environ.get("BLUEHOUR_LIBMPV_DIR"), os.getcwd(), here)):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory") and os.path.isdir(folder):
            try:
                os.add_dll_directory(folder)
            except OSError:
                pass


def python_args():
    """Interpreter command used to start the player and tools in a child process."""
    return [sys.executable, "-u", "-m", "bluehour"]
