import os
import tempfile
import unittest

from bluehour import gamepad as G


class FakeBackend:
    def __init__(self):
        self.pads = {}

    def present_ids(self):
        return sorted(self.pads)

    def name(self, j):
        return self.pads[j]["name"]

    def is_gamepad(self, j):
        return self.pads[j]["gamepad"]

    def raw(self, j):
        p = self.pads[j]
        return list(p["buttons"]), list(p["axes"]), list(p["hats"])

    def pressed(self, j):
        p = self.pads[j]
        return G.inputs_pressed(p["gp"] if p["gamepad"] else None, p["buttons"], p["axes"], p["hats"])


def pad(name="Xbox One", gamepad=True, **kw):
    d = dict(name=name, gamepad=gamepad, gp=[0] * 15, buttons=[0] * 12, axes=[0.0] * 4, hats=[0])
    d.update(kw)
    return d


class InputSpecTests(unittest.TestCase):
    def test_specs(self):
        s = G.inputs_pressed([1, 0, 0], [0, 1], [0.9, -0.9, 0.1, -1.0], [8, 0])
        self.assertEqual(s, {"gp:0", "button:1", "axis:0:+", "axis:1:-", "axis:3:-", "hat:0:8"})

    def test_diagonal_hat(self):
        self.assertEqual(G.inputs_pressed(None, [], [], [5]), {"hat:0:1", "hat:0:4"})


class PollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "sub", "gamepad.json")
        self.msgs = []
        self.fb = FakeBackend()

    def make(self):
        return G.GamepadInput(self.fb, self.cfg, say=self.msgs.append)

    def gp(self, *down):
        g = [0] * 15
        for i in down:
            g[i] = 1
        self.fb.pads[0]["gp"] = g

    def test_default_mapping_ignores_buttons_held_at_connect(self):
        self.fb.pads[0] = pad(gp=[1] + [0] * 14)
        gi = self.make()
        self.assertEqual(gi.poll(0.0), [])
        self.assertEqual(gi.poll(0.1), [])
        self.assertIn("default gamepad mapping", self.msgs[0])

    def test_edges_and_combos(self):
        self.fb.pads[0] = pad()
        gi = self.make()
        gi.poll(0.0)
        self.gp(0)
        self.assertEqual(gi.poll(0.3), ["pause"])
        self.assertEqual(gi.poll(0.4), [])
        self.gp(3)
        self.assertEqual(gi.poll(0.5), ["proj"])
        self.gp(4, 7)
        self.assertEqual(sorted(gi.poll(0.6)), ["long_back", "position"])

    def test_dpad_repeats_but_buttons_do_not(self):
        self.fb.pads[0] = pad()
        gi = self.make()
        gi.poll(0.0)
        got = []
        for t in (10.0, 10.2, 10.5, 10.55, 10.7):
            self.gp(14)
            got += gi.poll(t)
        self.assertEqual(got, ["seek_back"] * 3)
        got = []
        for t in (12.0, 12.2, 13.0):
            self.gp(0)
            got += gi.poll(t)
        self.assertEqual(got, ["pause"])

    def test_unplug_is_reported(self):
        self.fb.pads[0] = pad()
        gi = self.make()
        gi.poll(0.0)
        del self.fb.pads[0]
        gi.poll(5.0)
        self.assertTrue(any("disconnected" in m for m in self.msgs))

    def test_unmapped_pad_hints_once_then_saved_mapping_works(self):
        self.fb.pads[1] = pad("raphnet Classic", gamepad=False, axes=[0, 0, -1.0, 0])
        gi = self.make()
        gi.poll(0.0)
        self.assertTrue(any("--pad-config" in m for m in self.msgs))
        self.fb.pads[1]["buttons"][3] = 1
        self.assertEqual(gi.poll(0.2), [])
        G.save_config(self.cfg, {"raphnet Classic": {"pause": "button:3", "seek_fwd": "hat:0:2",
                                                      "vol_up": "axis:1:-", "mute": "axis:2:+"}})
        self.fb.pads[1]["buttons"][3] = 0
        gi = self.make()
        gi.poll(0.0)
        self.fb.pads[1]["buttons"][3] = 1
        self.assertEqual(gi.poll(0.1), ["pause"])
        self.fb.pads[1]["buttons"][3] = 0
        self.fb.pads[1]["hats"] = [2]
        self.assertEqual(gi.poll(0.2), ["seek_fwd"])
        self.fb.pads[1]["hats"] = [0]
        self.fb.pads[1]["axes"] = [0, -0.95, -1.0, 0]
        self.assertEqual(gi.poll(0.3), ["vol_up"])
        self.fb.pads[1]["axes"] = [0, 0, 1.0, 0]
        self.assertEqual(gi.poll(0.4), ["mute"])


class LearnTests(unittest.TestCase):
    @staticmethod
    def state(spec):
        b, a, h = [0] * 10, [0.0, 0.0, -1.0], [0]
        if spec:
            kind = spec.split(":")
            if kind[0] == "button":
                b[int(kind[1])] = 1
            elif kind[0] == "hat":
                h = [int(kind[2])]
            else:
                a[int(kind[1])] = 1.0
        return b, a, h

    def run_learn(self, queue, timeout=1.0):
        clock = [0.0]

        def now():
            clock[0] += 0.01
            return clock[0]

        class Backend:
            def raw(self, j):
                return queue.pop(0) if queue else LearnTests.state(None)

        lines = []
        return G.learn_mapping(Backend(), 0, say=lines.append, now_fn=now, sleep_fn=lambda s: None,
                               timeout=timeout), lines

    def test_full_mapping(self):
        specs = ["button:0", "button:1", "hat:0:8", "hat:0:2", "hat:0:1", "hat:0:4",
                 "button:4", "button:5", "axis:2:+", "button:6", "button:7", "button:8"]
        queue = [self.state(None)]
        for sp in specs:
            queue += [self.state(None)] * 3 + [self.state(sp)] * 2
        mapping, _ = self.run_learn(queue)
        self.assertEqual([mapping[a] for a in G.ACTIONS], specs)

    def test_skip_and_duplicate(self):
        queue = [self.state(None)] + ([self.state(None)] * 3 + [self.state("button:0")] * 2) * 2
        mapping, lines = self.run_learn(queue, timeout=0.5)
        self.assertEqual(mapping, {"pause": "button:0"})
        self.assertTrue(any("already used" in l for l in lines))
        self.assertTrue(any("skipped" in l for l in lines))


class ConfigTests(unittest.TestCase):
    def test_roundtrip_creates_folder_and_survives_garbage(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "a", "b", "gamepad.json")
        G.save_config(p, {"X": {"pause": "button:1"}})
        self.assertEqual(G.load_config(p), {"X": {"pause": "button:1"}})
        self.assertEqual(G.load_config(os.path.join(d, "missing.json")), {})
        with open(p, "w") as fh:
            fh.write("{not json")
        self.assertEqual(G.load_config(p), {})

    def test_default_path_is_per_user(self):
        self.assertTrue(G.default_path().replace("\\", "/").endswith("bluehour/gamepad.json"))


if __name__ == "__main__":
    unittest.main()
