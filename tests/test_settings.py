import json
import os
import tempfile
import unittest

from bluehour import control, settings
from bluehour.player import build_parser


class ParityTests(unittest.TestCase):
    """The GUI is generated from settings.FIELDS, so every command-line option must be there."""

    def setUp(self):
        self.parser = build_parser()
        self.dests = {a.dest for a in self.parser._actions}

    def test_every_option_is_a_setting_a_tool_or_deliberately_excluded(self):
        tool_dests = {v[0].lstrip("-").replace("-", "_") for v in settings.TOOLS.values()}
        covered = {f.name for f in settings.FIELDS} | tool_dests | settings.NOT_SETTINGS
        self.assertEqual(self.dests - covered, set(), "options with no GUI control")
        self.assertEqual(covered - self.dests, set(), "GUI settings that the command line does not know")

    def test_flags_match_the_parser(self):
        flags = {s for a in self.parser._actions for s in a.option_strings}
        for f in settings.FIELDS:
            self.assertIn(f.flag, flags)
        for flag, _label, _help in settings.TOOLS.values():
            self.assertIn(flag, flags)

    def test_defaults_match_the_parser(self):
        ns = self.parser.parse_args([])
        for f in settings.FIELDS:
            parsed = getattr(ns, f.name)
            expected = None if f.auto and f.default in ("auto", "") else f.default
            if f.name in ("proj", "stereo"):
                expected = None
            if f.name in ("audio_device", "pad_file"):
                expected = None
            self.assertEqual(parsed, expected, f.name)

    def test_choices_match_the_parser(self):
        by_dest = {a.dest: a for a in self.parser._actions}
        for f in settings.FIELDS:
            if f.kind == "choice":
                parser_choices = tuple(by_dest[f.name].choices)
                self.assertEqual(tuple(c for c in f.choices if c != "auto" or "auto" in parser_choices), parser_choices)

    def test_every_generated_command_line_is_accepted_by_the_real_parser(self):
        values = settings.defaults()
        values.update(proj="vr360", stereo="ou", swap_eyes=True, rotate="ccw", screen_width=7.5, distance=2.5,
                      ipd=60.5, fov_scale=1.1, k=[1.0, -0.2, 0.3, -0.05], ca=0.01, monitor=2, windowed=True,
                      tracking="mouse", axis_map="-x,y,-z", no_led_enable=True, position="wii", move_scale=2.0,
                      camera=1, cam_fov=80.0, cam_distance=1.2, cam_threshold=200, cam_axis_map="-x,y,z",
                      wii="both", wii_swap=True, wii_ir_level=5, wii_fov=50.0, wii_distance=1.5,
                      wii_axis_map="x,-y,z", no_gamepad=True, pad_file="C:\\x y\\pad.json", volume=100.0,
                      hwdec="no", audio_device="wasapi/{abc}", debug=True)
        argv = settings.to_argv(values, ["-odd name.mp4", "b.mkv"])
        ns = self.parser.parse_args(argv)
        self.assertEqual(ns.files, ["-odd name.mp4", "b.mkv"])
        self.assertTrue(ns.control)
        for f in settings.FIELDS:
            got = getattr(ns, f.name)
            self.assertEqual(got, values[f.name], f.name)

    def test_defaults_produce_a_minimal_command_line(self):
        self.assertEqual(settings.to_argv(settings.defaults(), ["a.mp4"]), ["--control", "--", "a.mp4"])
        self.assertEqual(settings.to_argv(settings.defaults(), [], control=False), [])


class CoerceTests(unittest.TestCase):
    def test_ranges_and_types(self):
        self.assertEqual(settings.coerce("ipd", "64"), 64.0)
        self.assertEqual(settings.coerce("wii_ir_level", 4.0), 4)
        for name, bad in (("ipd", 10), ("ipd", "abc"), ("ipd", float("nan")), ("ipd", True), ("proj", "cube"),
                          ("k", [1, 2, 3]), ("k", [1, 2, 3, "x"]), ("windowed", "yes"), ("camera", 99),
                          ("axis_map", "x,y"), ("axis_map", "x,y,q"), ("hwdec", "a\nb"), ("nope", 1)):
            with self.assertRaises(ValueError, msg="%s=%r" % (name, bad)):
                settings.coerce(name, bad)

    def test_auto_values(self):
        self.assertIsNone(settings.coerce("monitor", None))
        self.assertIsNone(settings.coerce("monitor", ""))
        self.assertEqual(settings.coerce("proj", "auto"), "auto")
        self.assertEqual(settings.coerce("audio_device", ""), "")

    def test_clean_drops_unknown_and_invalid(self):
        out = settings.clean({"ipd": 9999, "proj": "flat", "bogus": 1, "k": [1, 1, 1, 1]})
        self.assertEqual(out["ipd"], 63.5)
        self.assertEqual(out["proj"], "flat")
        self.assertNotIn("bogus", out)

    def test_state_file_roundtrip_and_garbage(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "sub", "gui.json")
        state = settings.load_state(p)
        state["settings"]["ipd"] = 62.0
        state["playlist"] = ["a.mp4"]
        state["presets"] = {"x": {"ipd": 60.0}}
        settings.save_state(state, p)
        again = settings.load_state(p)
        self.assertEqual((again["settings"]["ipd"], again["playlist"]), (62.0, ["a.mp4"]))
        self.assertEqual(again["presets"]["x"]["ipd"], 60.0)
        with open(p, "w") as fh:
            fh.write("[1,2")
        self.assertEqual(settings.load_state(p)["settings"], settings.defaults())


class ControlTests(unittest.TestCase):
    def test_valid_commands(self):
        for cmd in ({"cmd": "action", "name": "pause"}, {"cmd": "set", "name": "mute", "value": True},
                    {"cmd": "set", "name": "k", "value": [1, 0.2, 0.2, 0]}, {"cmd": "seek", "value": 5},
                    {"cmd": "load", "files": ["a.mp4"], "mode": "append"}, {"cmd": "play_index", "index": 2},
                    {"cmd": "quit"}):
            self.assertEqual(control.parse_command(json.dumps(cmd))["cmd"], cmd["cmd"])

    def test_invalid_commands(self):
        for line in ("nope", "[]", '{"cmd": 1}', '{"cmd":"action","name":"x"}',
                     '{"cmd":"set","name":"windowed","value":true}',
                     '{"cmd":"set","name":"pause","value":"yes"}', '{"cmd":"seek","value":"1"}',
                     '{"cmd":"seek","value":1,"mode":"sideways"}', '{"cmd":"load","files":[]}',
                     '{"cmd":"play_index","index":-1}', '{"cmd":"reboot"}'):
            with self.assertRaises(ValueError, msg=line):
                control.parse_command(line)

    def test_every_action_names_a_real_key(self):
        glfw_keys = {"SPACE", "LEFT", "RIGHT", "UP", "DOWN", "PAGE_UP", "PAGE_DOWN", "M", "N", "P", "T", "A", "R", "V",
                     "S", "X", "F", "1", "2", "3", "4", "0", "9", "MINUS", "EQUAL", "LEFT_BRACKET", "RIGHT_BRACKET",
                     "SEMICOLON", "APOSTROPHE", "COMMA", "PERIOD"}
        self.assertTrue(set(control.ACTION_KEYS.values()) <= glfw_keys)


class PlayerHooksTests(unittest.TestCase):
    """App._apply_command with a stand-in object: no window, no mpv."""

    def setUp(self):
        import types
        from bluehour import player
        self.player = player
        player.glfw = types.SimpleNamespace(PRESS=1, set_window_should_close=lambda *a: self.closed.append(a),
                                            **{"KEY_" + v: i for i, v in enumerate(set(control.ACTION_KEYS.values()))})
        self.closed, self.keys = [], []
        mpv = types.SimpleNamespace(volume=80.0, pause=False, mute=False, path="/v/movie_360_ou.mp4",
                                    command=lambda *a: self.keys.append(a), playlist_pos=0,
                                    loadfile=lambda *a: self.keys.append(("loadfile",) + a))
        self.app = types.SimpleNamespace(
            proj=0, stereo=0, swap=0, rotate=0, screen_w=4.0, dist=3.0, ipd=0.0635, tan_half=0.9, k=[1, .2, .2, 0],
            ca=0.005, pos_mode=0, pos_scale=1.0, player=mpv, files=["a.mp4"], win="W",
            args=types.SimpleNamespace(proj=None, stereo=None),
            _on_key=lambda win, key, sc, act, mods: self.keys.append(("key", key)),
            _current_path=lambda: "/v/movie_360_ou.mp4")
        self.app._apply_set = lambda n, v: player.App._apply_set(self.app, n, v)

    def apply(self, cmd):
        self.player.App._apply_command(self.app, cmd)

    def test_set_commands_change_the_right_fields(self):
        self.apply({"cmd": "set", "name": "ipd", "value": 65.0})
        self.assertAlmostEqual(self.app.ipd, 0.065)
        self.apply({"cmd": "set", "name": "proj", "value": "curved"})
        self.assertEqual(self.app.proj, 1)
        self.apply({"cmd": "set", "name": "proj", "value": "auto"})
        self.assertEqual(self.app.proj, 3)                      # movie_360_ou -> VR360
        self.apply({"cmd": "set", "name": "stereo", "value": "auto"})
        self.assertEqual(self.app.stereo, 2)                    # ... over-under
        self.apply({"cmd": "set", "name": "rotate", "value": "flip"})
        self.assertEqual(self.app.rotate, 2)
        self.apply({"cmd": "set", "name": "k", "value": [1, .3, .1, 0]})
        self.assertEqual(self.app.k, [1, .3, .1, 0])
        self.apply({"cmd": "set", "name": "position", "value": "neck"})
        self.assertEqual(self.player.POS_NAMES[self.app.pos_mode], "neck")
        self.apply({"cmd": "set", "name": "volume", "value": 55.0})
        self.assertEqual(self.app.player.volume, 55.0)
        self.apply({"cmd": "set", "name": "pause", "value": True})
        self.assertTrue(self.app.player.pause)

    def test_actions_and_seek_and_load(self):
        self.apply({"cmd": "action", "name": "pause"})
        self.assertEqual(self.keys[-1][0], "key")
        self.apply({"cmd": "seek", "value": 12.0, "mode": "absolute"})
        self.assertEqual(self.keys[-1], ("seek", 12.0, "absolute"))
        self.apply({"cmd": "load", "files": ["b_180_sbs.mp4", "c.mp4"], "mode": "replace"})
        self.assertEqual(self.app.files, ["b_180_sbs.mp4", "c.mp4"])
        self.assertEqual((self.app.proj, self.app.stereo), (2, 1))
        self.apply({"cmd": "quit"})
        self.assertTrue(self.closed)


if __name__ == "__main__":
    unittest.main()
