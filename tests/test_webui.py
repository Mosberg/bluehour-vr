import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest

from bluehour import control, settings, webui

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_player.py")


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.runner = webui.Runner([sys.executable, "-u", FAKE])
        self.app = webui.App(self.runner, os.path.join(self.tmp, "gui.json"), os.path.join(self.tmp, "pad.json"),
                             token="secret-token")
        self.server = webui.make_server(self.app, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.video = os.path.join(self.tmp, "clip_180_sbs.mp4")
        open(self.video, "wb").close()

    def tearDown(self):
        self.runner.shutdown()
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, headers=None, token="secret-token", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or "127.0.0.1:%d" % self.port}
        if token is not None:
            h["X-Bluehour-Token"] = token
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def wait(self, predicate, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            _, st = self.call("GET", "/api/state")
            if predicate(st):
                return st
            time.sleep(0.05)
        self.fail("timed out waiting; last state: %r" % (st,))


class SecurityTests(ServerCase):
    def test_api_needs_token(self):
        self.assertEqual(self.call("GET", "/api/state", token=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/state", token="wrong")[0], 401)
        self.assertEqual(self.call("GET", "/api/state")[0], 200)

    def test_foreign_host_is_refused(self):
        self.assertEqual(self.call("GET", "/api/state", host="evil.example:80")[0], 403)
        self.assertEqual(self.call("GET", "/", host="evil.example:80")[0], 403)

    def test_foreign_origin_and_non_json_posts_are_refused(self):
        self.assertEqual(self.call("POST", "/api/stop", {}, {"Origin": "http://evil.example"})[0], 403)
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/stop", "x=1", {"X-Bluehour-Token": "secret-token",
                                                   "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(conn.getresponse().status, 415)

    def test_static_files_and_headers(self):
        status, body = self.call("GET", "/", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b"Bluehour", body)
        self.assertEqual(self.call("GET", "/../secret", token=None)[0], 404)
        self.assertEqual(self.call("GET", "/app.js", token=None)[0], 200)
        self.assertEqual(self.call("GET", "/app.css", token=None)[0], 200)


class SettingsApiTests(ServerCase):
    def test_schema_matches_settings(self):
        status, data = self.call("GET", "/api/schema")
        self.assertEqual(status, 200)
        self.assertEqual([f["name"] for f in data["fields"]], [f.name for f in settings.FIELDS])
        self.assertEqual([t["id"] for t in data["tools"]], list(settings.TOOLS))

    def test_save_and_reload_settings(self):
        status, _ = self.call("POST", "/api/settings", {"settings": {"ipd": 66.5, "proj": "vr180",
                                                               "k": [1, .3, .2, 0]}})
        self.assertEqual(status, 200)
        _, st = self.call("GET", "/api/state")
        self.assertEqual(st["settings"]["ipd"], 66.5)
        self.assertEqual(settings.load_state(self.app.state_file)["settings"]["proj"], "vr180")

    def test_invalid_settings_are_rejected_with_a_readable_message(self):
        status, data = self.call("POST", "/api/settings", {"settings": {"ipd": 500}})
        self.assertEqual(status, 400)
        self.assertIn("IPD", data["error"])
        self.assertEqual(self.call("POST", "/api/settings", {"settings": {"bogus": 1}})[0], 400)
        self.assertEqual(self.call("POST", "/api/settings", {"settings": {"axis_map": "x;y;z"}})[0], 400)

    def test_playlist_and_presets(self):
        self.call("POST", "/api/playlist", {"playlist": [self.video, "https://example.org/v.mp4"]})
        self.call("POST", "/api/settings", {"settings": {"ipd": 60.0}})
        self.assertEqual(self.call("POST", "/api/presets", {"action": "save", "name": "Cinema"})[0], 200)
        self.call("POST", "/api/settings", {"settings": {"ipd": 70.0}})
        status, data = self.call("POST", "/api/presets", {"action": "load", "name": "Cinema"})
        self.assertEqual((status, data["settings"]["ipd"]), (200, 60.0))
        self.assertEqual(self.call("POST", "/api/presets", {"action": "load", "name": "Nope"})[0], 404)
        self.call("POST", "/api/presets", {"action": "delete", "name": "Cinema"})
        _, st = self.call("GET", "/api/state")
        self.assertEqual(st["presets"], [])
        self.assertEqual(len(st["playlist"]), 2)


class FileBrowserTests(ServerCase):
    def test_listing_marks_media_and_sorts_folders_first(self):
        os.mkdir(os.path.join(self.tmp, "afolder"))
        open(os.path.join(self.tmp, "notes.txt"), "w").close()
        status, data = self.call("GET", "/api/fs?path=" + self.tmp)
        self.assertEqual(status, 200)
        names = [e["name"] for e in data["entries"]]
        self.assertEqual(names[0], "afolder")
        media = {e["name"]: e["media"] for e in data["entries"]}
        self.assertTrue(media["clip_180_sbs.mp4"])
        self.assertFalse(media["notes.txt"])
        self.assertEqual(self.call("GET", "/api/fs?path=/definitely/not/here")[0], 400)


class PlayerFlowTests(ServerCase):
    def start(self):
        status, data = self.call("POST", "/api/play", {"files": [self.video]})
        self.assertEqual((status, data.get("started")), (200, True), data)
        return self.wait(lambda s: s["player_state"] is not None)

    def test_play_passes_settings_and_files(self):
        self.call("POST", "/api/settings", {"settings": {"proj": "vr180", "ipd": 64.0, "windowed": True}})
        self.start()
        _, st = self.call("GET", "/api/state")
        text = " ".join(e["text"] for e in st["log"])
        self.assertIn("--proj=vr180", text)
        self.assertIn("--ipd=64.0", text)
        self.assertIn("--windowed", text)
        self.assertIn("--control", text)
        self.assertIn(self.video, text)

    def test_live_commands_reach_the_player(self):
        self.start()
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "set", "name": "ipd", "value": 61.0})[0], 200)
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "action", "name": "pause"})[0], 200)
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "seek", "value": 42})[0], 200)
        st = self.wait(lambda s: s["player_state"] and s["player_state"]["ipd"] == 61.0 and s["player_state"]["pause"]
                       and s["player_state"]["time"] == 42.0)
        self.assertTrue(st["player_running"])

    def test_bad_commands_are_rejected_before_reaching_the_player(self):
        self.start()
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "set", "name": "ipd", "value": 999})[0], 400)
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "set", "name": "monitor", "value": 1})[0], 400)
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "action", "name": "format_disk"})[0], 400)
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "load", "files": ["/no/such.mp4"]})[0], 400)

    def test_cannot_start_twice_and_stop_works(self):
        self.start()
        self.assertEqual(self.call("POST", "/api/play", {"files": [self.video]})[0], 409)
        self.assertEqual(self.call("POST", "/api/stop", {})[0], 200)
        self.wait(lambda s: not s["player_running"])
        self.assertEqual(self.call("POST", "/api/command", {"cmd": "action", "name": "pause"})[0], 409)

    def test_missing_files_and_empty_playlist(self):
        self.assertEqual(self.call("POST", "/api/play", {"files": ["/no/such/file.mp4"]})[0], 400)
        self.assertEqual(self.call("POST", "/api/play", {})[0], 400)

    def test_player_exit_is_noticed(self):
        self.start()
        self.runner.player.kill()
        st = self.wait(lambda s: not s["player_running"] and "player" in s["last_exit"])
        self.assertIn("player", st["last_exit"])


class ToolTests(ServerCase):
    def test_detect_monitors_and_cameras(self):
        _, mon = self.call("GET", "/api/detect/monitors")
        self.assertEqual([m["index"] for m in mon["monitors"]], [0, 1])
        self.assertTrue(mon["monitors"][0]["primary"])
        self.assertEqual((mon["monitors"][1]["width"], mon["monitors"][1]["hz"]), (1920, 75))
        _, cam = self.call("GET", "/api/detect/cameras")
        self.assertEqual(cam["cameras"], [{"index": 0, "width": 752, "height": 480, "dk2": True}])

    def test_doctor_result_is_parsed(self):
        self.assertEqual(self.call("POST", "/api/tool", {"tool": "doctor"})[0], 200)
        st = self.wait(lambda s: s["doctor"] is not None)
        self.assertEqual(st["doctor"][0]["name"], "Python")

    def test_long_running_tool_can_be_stopped(self):
        self.assertEqual(self.call("POST", "/api/tool", {"tool": "pad_test"})[0], 200)
        self.wait(lambda s: s["tool_running"])
        self.assertEqual(self.call("POST", "/api/tool", {"tool": "pad_test"})[0], 409)
        self.call("POST", "/api/tool", {"action": "stop"})
        self.wait(lambda s: not s["tool_running"])
        self.assertEqual(self.call("POST", "/api/tool", {"tool": "nope"})[0], 400)


class GamepadApiTests(ServerCase):
    def test_mapping_roundtrip_and_validation(self):
        _, data = self.call("GET", "/api/gamepad")
        self.assertIn("pause", [a["id"] for a in data["actions"]])
        good = {"raphnet Classic": {"pause": "button:3", "seek_fwd": "hat:0:2", "vol_up": "axis:1:-"}}
        self.assertEqual(self.call("POST", "/api/gamepad", {"config": good})[0], 200)
        _, data = self.call("GET", "/api/gamepad")
        self.assertEqual(data["config"], good)
        for bad in ({"X": {"pause": "button:x"}}, {"X": {"explode": "button:1"}}, {"X": {"pause": "hat:0:3"}}):
            self.assertEqual(self.call("POST", "/api/gamepad", {"config": bad})[0], 400)


class ProtocolTests(unittest.TestCase):
    def test_state_roundtrip(self):
        self.assertEqual(control.decode_state(control.encode_state({"a": 1})), {"a": 1})
        self.assertIsNone(control.decode_state("hello"))
        self.assertIsNone(control.decode_state("@state {broken"))


if __name__ == "__main__":
    unittest.main()
