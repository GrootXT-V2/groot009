import importlib.util
import math
import unittest
from pathlib import Path


source = Path(__file__).with_name("buddy.py")
if not source.exists():
    source = Path(__file__).resolve().parents[1] / "groot" / "buddy.py"
spec = importlib.util.spec_from_file_location("fox_buddy", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Buddy = module.Buddy


class RecordingCanvas(module.Canvas):
    def __init__(self):
        self.depth = 0
        self.paths = 0

    def save(self): self.depth += 1
    def restore(self): self.depth -= 1
    def translate(self, *args): pass
    def rotate(self, *args): pass
    def scale(self, *args): pass
    def scale_xy(self, *args): pass
    def clip(self, *args): pass
    def fill_rect(self, *args): pass
    def text(self, *args, **kwargs): pass
    def fill_stroke(self, shape, *args):
        self.paths += 1
        assert all(math.isfinite(v) for cmd in shape.cmds for v in cmd[1:])


class FoxMotionTests(unittest.TestCase):
    def test_planted_paw_matches_screen_motion(self):
        for direction in (-1, 1):
            buddy = Buddy(style="fox")
            buddy.step = 0.3
            start = buddy.x
            paw = buddy._rf_paw(66, 0, buddy.step, True, 291)
            pose = {}
            buddy._walk_toward(start + direction * 100, 1, pose)
            after = buddy._rf_paw(66, 0, buddy.step, True, 291)
            self.assertEqual(after[1], 291)
            self.assertAlmostEqual((after[0] - paw[0]) * buddy.scale, abs(buddy.x - start))

    def test_swing_clears_floor_and_cycle_is_continuous(self):
        self.assertLess(Buddy._rf_paw(66, 0, 0.81 * math.tau, True, 291)[1], 291)
        for boundary in (0.62, 1):
            before = Buddy._rf_paw(66, 0, (boundary - 1e-8) * math.tau, True, 291)
            after = Buddy._rf_paw(66, 0, (boundary + 1e-8) * math.tau, True, 291)
            self.assertLess(math.dist(before, after), 1e-4)

    def test_movement_does_not_stop_at_zero_leg_swing(self):
        buddy = Buddy(style="fox")
        buddy.state = "idle"
        now = buddy.action["start"] + 1
        buddy._return_fox_to_corner("left")
        buddy._fox_departure = -1
        buddy.step = math.pi - 2 * buddy.speed * math.tau * 0.62 / 30 / buddy.scale
        buddy.tick(now)
        self.assertTrue(buddy.pose["walking"])
        self.assertAlmostEqual(buddy.pose["legs"], 0)
        self.assertEqual(buddy.pose["lean"], 0)

    def test_draw_states_and_activities(self):
        buddy = Buddy(style="fox")
        buddy.caption = ""
        for state in ("idle", "listening", "thinking", "speaking"):
            buddy.state = state
            for activity in (None, "run", "football", "butterfly", "wave", "sleep"):
                if activity:
                    buddy._start_activity(activity)
                else:
                    buddy.activity = None
                buddy.tick()
                canvas = RecordingCanvas()
                buddy.draw(canvas)
                self.assertEqual(canvas.depth, 0)
                self.assertGreater(canvas.paths, 100)


if __name__ == "__main__":
    unittest.main()
