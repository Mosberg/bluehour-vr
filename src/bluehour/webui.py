"""The Bluehour GUI: a small local web app that starts the player, controls it live and edits every setting.

Run it with `bluehour-gui` (or `python -m bluehour.webui`). It listens on 127.0.0.1 only. Every API call needs a
random token that is part of the address it opens, and requests with a foreign Host or Origin header are refused,
so other web pages cannot drive it. Standard library only.
"""
import argparse
import collections
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, control, settings
from .paths import config_dir, python_args

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")
STATIC_FILES = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                "app.css": "text/css; charset=utf-8", "logo-dark.svg": "image/svg+xml", "logo.svg": "image/svg+xml",
                "favicon.svg": "image/svg+xml", "icon.svg": "image/svg+xml"}
MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg",
             ".ogv", ".3gp", ".vob", ".iso", ".mp3", ".flac", ".wav", ".m3u", ".m3u8"}
URL_RE = re.compile(r"^(https?|rtsp|rtmp|mms)://\S+$", re.I)
SPEC_RE = re.compile(r"^(gp|button):\d{1,3}$|^hat:\d{1,2}:(1|2|4|8)$|^axis:\d{1,3}:[+-]$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Runner:
    """Owns the player process and one helper-tool process, their output, and the player's last reported state."""

    def __init__(self, command_prefix=None, log_size=1000):
        self.prefix = list(command_prefix or python_args())
        self.lock = threading.Lock()
        self.log = collections.deque(maxlen=log_size)
        self.seq = 0
        self.player = None
        self.tool = None
        self.tool_name = None
        self.player_state = None
        self.player_state_time = 0.0
        self.last_exit = {}
        self.doctor = None

    # ---- output ----
    def _add(self, src, text):
        with self.lock:
            self.seq += 1
            self.log.append({"n": self.seq, "src": src, "text": text[:2000]})

    def _pump(self, proc, src):
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if src == "player":
                state = control.decode_state(line)
                if state is not None:
                    with self.lock:
                        self.player_state, self.player_state_time = state, time.time()
                    continue
            elif line.startswith("@doctor "):
                try:
                    self.doctor = json.loads(line[len("@doctor "):])
                except ValueError:
                    pass
                continue
            self._add(src, line)
        code = proc.wait()
        with self.lock:
            self.last_exit[src] = code
            if src == "player" and self.player is proc:
                self.player = None
                self.player_state = None
            if src == "tool" and self.tool is proc:
                self.tool = None
        self._add("system", "%s exited with code %s" % ("Player" if src == "player" else "Tool", code))

    def _spawn(self, argv, src):
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                                creationflags=NO_WINDOW)
        threading.Thread(target=self._pump, args=(proc, src), daemon=True).start()
        return proc

    # ---- player ----
    def player_running(self):
        return self.player is not None and self.player.poll() is None

    def start_player(self, values, files):
        if self.player_running():
            raise ApiError("The player is already running.", 409)
        argv = self.prefix + settings.to_argv(values, files, control=True)
        self._add("system", "Starting: bluehour " + " ".join(argv[len(self.prefix):]))
        with self.lock:
            self.player_state = None
        self.player = self._spawn(argv, "player")

    def send(self, cmd):
        if not self.player_running():
            raise ApiError("The player is not running.", 409)
        try:
            self.player.stdin.write(json.dumps(cmd) + "\n")
            self.player.stdin.flush()
        except (OSError, ValueError):
            raise ApiError("The player is not accepting commands.", 409) from None

    def stop_player(self, timeout=4.0):
        proc = self.player
        if proc is None or proc.poll() is not None:
            return
        try:
            self.send({"cmd": "quit"})
        except ApiError:
            pass
        self._wait_or_kill(proc, timeout)

    @staticmethod
    def _wait_or_kill(proc, timeout):
        try:
            proc.wait(timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.terminate()
        try:
            proc.wait(2.0)
        except subprocess.TimeoutExpired:
            proc.kill()

    # ---- tools ----
    def tool_running(self):
        return self.tool is not None and self.tool.poll() is None

    def start_tool(self, tool_id, values):
        if tool_id not in settings.TOOLS:
            raise ApiError("Unknown tool.")
        if self.tool_running():
            raise ApiError("Another tool is still running. Stop it first.", 409)
        flag = settings.TOOLS[tool_id][0]
        argv = self.prefix + [flag] + settings.to_argv(values, (), control=False)
        self._add("system", "Running: bluehour " + " ".join(argv[len(self.prefix):]))
        if tool_id == "doctor":
            self.doctor = None
        self.tool_name = tool_id
        self.tool = self._spawn(argv, "tool")

    def stop_tool(self):
        proc = self.tool
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.close()
            except OSError:
                pass
            self._wait_or_kill(proc, 0.5)

    def run_tool_capture(self, tool_id, values, timeout=30.0):
        """Run a short tool to completion and return its output lines."""
        flag = settings.TOOLS[tool_id][0]
        argv = self.prefix + [flag] + settings.to_argv(values, (), control=False)
        try:
            done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise ApiError("That took too long and was stopped.", 504) from None
        return (done.stdout + done.stderr).splitlines(), done.returncode

    def shutdown(self):
        self.stop_tool()
        self.stop_player()

    # ---- snapshot for the UI ----
    def snapshot(self, since=0):
        with self.lock:
            log = [e for e in self.log if e["n"] > since]
            state = dict(self.player_state) if self.player_state else None
            age = time.time() - self.player_state_time if state else None
            return {"player_running": self.player_running(), "tool_running": self.tool_running(),
                    "tool": self.tool_name if self.tool_running() else None, "player_state": state,
                    "player_state_age": age, "log": log, "log_seq": self.seq, "doctor": self.doctor,
                    "last_exit": dict(self.last_exit)}


# ---------------------------------------------------------------------------------------------
# file browsing
# ---------------------------------------------------------------------------------------------

def list_roots():
    if os.name == "nt":
        return ["%s:\\" % c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists("%s:\\" % c)]
    return ["/"]


def browse(path):
    """Directory listing for the built-in file picker: folders first, then files, with a flag for media files."""
    home = os.path.expanduser("~")
    if not path:
        path = home
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise ApiError("That folder does not exist.")
    entries = []
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    is_dir = e.is_dir()
                    size = None if is_dir else e.stat().st_size
                except OSError:
                    continue
                ext = os.path.splitext(e.name)[1].lower()
                entries.append({"name": e.name, "dir": is_dir, "size": size,
                                "media": (not is_dir) and ext in MEDIA_EXT})
    except PermissionError:
        raise ApiError("You do not have permission to open that folder.", 403) from None
    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else None, "home": home, "roots": list_roots(),
            "sep": os.sep, "entries": entries[:5000]}


def check_files(files):
    """Local files must exist; web addresses must look like one. Returns the cleaned list or raises."""
    out, missing = [], []
    for f in files:
        if not isinstance(f, str) or not f.strip() or "\n" in f or "\x00" in f:
            raise ApiError("The playlist contains an invalid entry.")
        f = f.strip()
        if URL_RE.match(f):
            out.append(f)
        elif os.path.isfile(f):
            out.append(os.path.abspath(f))
        else:
            missing.append(f)
    if missing:
        raise ApiError("Not found: " + ", ".join(missing[:3]) + (" and more" if len(missing) > 3 else ""))
    return out


# ---------------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------------

class App:
    """Everything the handlers need, so tests can build a server with a fake player."""

    def __init__(self, runner=None, state_file=None, gamepad_file=None, token=None):
        self.runner = runner or Runner()
        self.state_file = state_file or settings.state_path()
        self.gamepad_file = gamepad_file
        self.token = token or secrets.token_urlsafe(24)
        self.state = settings.load_state(self.state_file)
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()

    def save(self):
        settings.save_state(self.state, self.state_file)

    def gamepad_path(self):
        from . import gamepad
        return self.gamepad_file or self.state["settings"].get("pad_file") or gamepad.default_path()


def json_body(handler):
    length = int(handler.headers.get("Content-Length") or 0)
    if length > 2_000_000:
        raise ApiError("That request is too large.", 413)
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        raise ApiError("The request was not valid JSON.") from None
    if not isinstance(data, dict):
        raise ApiError("The request must be a JSON object.")
    return data


def api_get(app, path, query):
    r = app.runner
    if path == "/api/schema":
        data = settings.schema()
        data["version"] = __version__
        data["platform"] = sys.platform
        return data
    if path == "/api/state":
        since = int(query.get("since", ["0"])[0] or 0)
        with app.lock:
            out = {"settings": app.state["settings"], "playlist": app.state["playlist"],
                   "presets": sorted(app.state["presets"])}
        out.update(r.snapshot(since))
        return out
    if path == "/api/fs":
        return browse(query.get("path", [""])[0])
    if path == "/api/detect/monitors":
        lines, _ = r.run_tool_capture("list_monitors", app.state["settings"])
        found = []
        for line in lines:
            m = re.match(r"^(\d+): (.*?)\s+(\d+)x(\d+) @ (\d+) Hz(\s+\(primary\))?\s*$", line)
            if m:
                found.append({"index": int(m.group(1)), "name": m.group(2), "width": int(m.group(3)),
                              "height": int(m.group(4)), "hz": int(m.group(5)), "primary": bool(m.group(6))})
        return {"monitors": found, "output": lines}
    if path == "/api/detect/cameras":
        lines, _ = r.run_tool_capture("list_cameras", app.state["settings"], timeout=60.0)
        found = []
        for line in lines:
            m = re.match(r"^camera (\d+): (\d+)x(\d+)(.*)$", line)
            if m:
                found.append({"index": int(m.group(1)), "width": int(m.group(2)), "height": int(m.group(3)),
                              "dk2": "DK2" in m.group(4)})
        return {"cameras": found, "output": lines}
    if path == "/api/gamepad":
        from . import gamepad
        file = app.gamepad_path()
        return {"file": file, "config": gamepad.load_config(file), "defaults": gamepad.DEFAULT_GAMEPAD,
                "actions": [{"id": a, "label": gamepad.LABELS[a]} for a in gamepad.ACTIONS]}
    raise ApiError("Not found.", 404)


def api_post(app, path, body):
    r = app.runner
    if path == "/api/settings":
        incoming = body.get("settings")
        if not isinstance(incoming, dict):
            raise ApiError("settings must be an object")
        clean, errors = {}, []
        for name, value in incoming.items():
            try:
                clean[name] = settings.coerce(name, value)
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            raise ApiError("; ".join(errors))
        with app.lock:
            app.state["settings"].update(clean)
            app.save()
            return {"settings": app.state["settings"]}
    if path == "/api/playlist":
        files = body.get("playlist")
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ApiError("playlist must be a list of text")
        with app.lock:
            app.state["playlist"] = [f.strip() for f in files if f.strip()][:2000]
            app.save()
        return {"playlist": app.state["playlist"]}
    if path == "/api/presets":
        action, name = body.get("action"), str(body.get("name", "")).strip()
        if not name or len(name) > 60:
            raise ApiError("Give the preset a name of up to 60 characters.")
        with app.lock:
            if action == "save":
                app.state["presets"][name] = dict(app.state["settings"])
            elif action == "load":
                if name not in app.state["presets"]:
                    raise ApiError("No preset with that name.", 404)
                app.state["settings"] = settings.clean(app.state["presets"][name])
            elif action == "delete":
                app.state["presets"].pop(name, None)
            else:
                raise ApiError("action must be save, load or delete")
            app.save()
            return {"settings": app.state["settings"], "presets": sorted(app.state["presets"])}
    if path == "/api/play":
        files = body.get("files")
        if files is None:
            files = app.state["playlist"]
        if not isinstance(files, list):
            raise ApiError("files must be a list")
        if not files:
            raise ApiError("Add a video to the playlist first.")
        files = check_files(files)
        r.start_player(app.state["settings"], files)
        return {"started": True}
    if path == "/api/stop":
        r.stop_player()
        return {"stopped": True}
    if path == "/api/command":
        cmd = control.parse_command(json.dumps(body)) if body else None
        if cmd is None:
            raise ApiError("Empty command.")
        if cmd["cmd"] == "load":
            cmd["files"] = check_files(cmd["files"])
        r.send(cmd)
        return {"sent": True}
    if path == "/api/tool":
        action = body.get("action", "start")
        if action == "stop":
            r.stop_tool()
            return {"stopped": True}
        r.start_tool(body.get("tool"), app.state["settings"])
        return {"started": True}
    if path == "/api/gamepad":
        from . import gamepad
        config = body.get("config")
        if not isinstance(config, dict):
            raise ApiError("config must be an object")
        for name, mapping in config.items():
            if not isinstance(mapping, dict):
                raise ApiError("Each controller needs a mapping.")
            for action, spec in mapping.items():
                if action not in gamepad.ACTIONS:
                    raise ApiError("Unknown action: %s" % action)
                if not isinstance(spec, str) or not SPEC_RE.match(spec):
                    raise ApiError("'%s' is not a valid control. Use for example button:3, hat:0:2 or axis:1:-." % spec)
        gamepad.save_config(app.gamepad_path(), config)
        return {"saved": True}
    if path == "/api/shutdown":
        app.shutdown_event.set()
        return {"bye": True}
    raise ApiError("Not found.", 404)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Bluehour"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        # ---- helpers ----
        def _allowed_host(self):
            host = (self.headers.get("Host") or "").lower()
            port = self.server.server_address[1]
            return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

        def _send(self, status, body, ctype, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data:; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, data):
            self._send(status, json.dumps(data).encode("utf-8"), "application/json", {"Cache-Control": "no-store"})

        def _authorised(self, post):
            if not self._allowed_host():
                raise ApiError("Forbidden host.", 403)
            if not hmac.compare_digest(self.headers.get("X-Bluehour-Token", ""), app.token):
                raise ApiError("Missing or wrong token. Open the address printed by bluehour-gui.", 401)
            if post:
                origin = self.headers.get("Origin")
                if origin and origin.lower() not in ("http://127.0.0.1:%d" % self.server.server_address[1],
                                                     "http://localhost:%d" % self.server.server_address[1]):
                    raise ApiError("Forbidden origin.", 403)
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    raise ApiError("Requests must be JSON.", 415)

        def _handle(self, post):
            url = urlparse(self.path)
            try:
                if url.path.startswith("/api/"):
                    self._authorised(post)
                    if post:
                        data = api_post(app, url.path, json_body(self))
                    else:
                        data = api_get(app, url.path, parse_qs(url.query))
                    self._json(200, data)
                elif not post:
                    self._static(url.path)
                else:
                    raise ApiError("Not found.", 404)
            except ApiError as exc:
                self._json(exc.status, {"error": str(exc)})
            except ValueError as exc:                       # control.parse_command and similar validation
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - never let one request kill the server
                self._json(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

        def _static(self, path):
            if not self._allowed_host():
                raise ApiError("Forbidden host.", 403)
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            if name not in STATIC_FILES:
                raise ApiError("Not found.", 404)
            with open(os.path.join(STATIC_DIR, name), "rb") as fh:
                body = fh.read()
            self._send(200, body, STATIC_FILES[name], {"Cache-Control": "no-cache"})

        def do_GET(self):
            self._handle(False)

        def do_POST(self):
            self._handle(True)

    return Handler


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return  # the browser went away mid-request; nothing to report
        super().handle_error(request, client_address)


def make_server(app, port=0):
    return QuietServer(("127.0.0.1", port), make_handler(app))


def find_app_browser():
    """A Chrome or Edge that can open the page as a plain app window (no tabs), or None."""
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge"]
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    if os.name == "nt":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(k)]
        for root in roots:
            for rel in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"):
                path = os.path.join(root, rel)
                if os.path.isfile(path):
                    return path
    return None


def open_window(url, app_window=True):
    exe = find_app_browser() if app_window else None
    if exe:
        try:
            subprocess.Popen([exe, "--app=" + url, "--window-size=1180,820"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            return
        except OSError:
            pass
    webbrowser.open(url)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bluehour-gui", description="Bluehour control panel (opens in your browser)")
    ap.add_argument("--port", type=int, default=0, help="port to listen on (default: any free port)")
    ap.add_argument("--no-browser", action="store_true", help="only print the address")
    ap.add_argument("--tab", action="store_true", help="open in a normal browser tab instead of an app window")
    ap.add_argument("--version", action="version", version="bluehour-gui " + __version__)
    args = ap.parse_args(argv)

    os.makedirs(config_dir(), exist_ok=True)
    app = App()
    server = make_server(app, args.port)
    url = "http://127.0.0.1:%d/?t=%s" % (server.server_address[1], app.token)
    print("Bluehour control panel: " + url)
    print("Close this window or press Ctrl+C to quit.")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if not args.no_browser:
        open_window(url, not args.tab)
    try:
        while thread.is_alive() and not app.shutdown_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        app.runner.shutdown()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
