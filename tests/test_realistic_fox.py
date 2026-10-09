import importlib.util
import math
import sys
import unittest
from pathlib import Path

root = Path(__file__).parent
if not (root / "groot" / "buddy.py").is_file():
    root = root.parent
spec = importlib.util.spec_from_file_location("realistic_buddy", root / "groot" / "buddy.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SpriteCanvas(module.Canvas):
    def __init__(self):
        self.frames = []
        self.paths = []
        self.scales = []
        self.texts = []
        self.depth = 0

    def save(self): self.depth += 1
    def restore(self): self.depth -= 1
    def translate(self, *args): pass
    def scale(self, *args): pass
    def scale_xy(self, *args): self.scales.append(args)
    def rotate(self, *args): pass
    def clip(self, *args): pass
    def text(self, x, y, text, size, color, bold=False): self.texts.append(text)
    def sprite(self, path, frame, columns, rows, x, y, w, h, opacity=1):
        self.frames.append((frame, y, w, h))
        self.paths.append(Path(path).name)
        assert Path(path).is_file()
        return True


class RealisticFoxTests(unittest.TestCase):
    def setUp(self):
        self.buddy = module.Buddy(style="fox")
        self.buddy.caption = ""
        self.buddy.pose = {"bob": 0, "lift": 0, "legs": 0, "lean": 0, "walking": False}
        self.buddy.blink_until = 0

    def test_walk_cycles_use_distance(self):
        self.buddy.pose["walking"] = True
        for frame in range(8):
            self.buddy.step = (frame + 0.1) * math.tau / 8
            self.assertEqual(self.buddy._fox_sprite_frame(100), frame)
        self.buddy.step += math.tau
        self.assertEqual(self.buddy._fox_sprite_frame(100), 7)

    def test_walk_frames_keep_the_same_screen_registration(self):
        b = self.buddy
        b.pose["walking"] = True
        rectangles = []
        for frame in range(8):
            b.step = (frame + 0.1) * math.tau / 8
            canvas = SpriteCanvas()
            b.draw(canvas, now=100)
            rectangles.append(canvas.frames[0][1:])
        self.assertEqual(len(set(rectangles)), 1)

    @unittest.skipUnless(sys.platform == "darwin", "Native PNG inspection uses AppKit")
    def test_packed_art_has_clear_gutters_and_registered_walk_silhouettes(self):
        from AppKit import NSBitmapImageRep

        path = root / "groot" / "assets" / "red-white-serious-fox.png"
        rep = NSBitmapImageRep.imageRepWithContentsOfFile_(str(path))
        self.assertEqual((rep.pixelsWide(), rep.pixelsHigh()), (2048, 2048))
        pixels, stride = bytes(rep.bitmapData()), rep.bytesPerRow()
        tops = []
        for frame in range(16):
            x0, y0 = frame % 4 * 512, frame // 4 * 512
            occupied = []
            for y in range(512):
                for x in range(512):
                    alpha = pixels[(y0 + y) * stride + (x0 + x) * 4 + 3]
                    if alpha:
                        self.assertTrue(16 <= x < 496 and 16 <= y < 496,
                                        f"Frame {frame} has pixels in its transparent gutter")
                    if alpha > 100:
                        occupied.append((x, y))
            self.assertGreater(len(occupied), 10000)
            if frame < 8:
                tops.append(min(y for x, y in occupied))
        self.assertLessEqual(max(tops) - min(tops), 2,
                             "Walking heads must not jump up and down between frames")

    def test_rest_and_session_states(self):
        b = self.buddy
        b.state = "idle"
        self.assertEqual(b._fox_sprite_frame(100), 12)
        b.state = "listening"
        self.assertEqual(b._fox_sprite_frame(100), 12)
        b.state = "speaking"
        b.mouth = [0.8] * 5
        self.assertEqual(b._fox_sprite_frame(100), 12)
        b.activity = {"name": "sleep"}
        self.assertEqual(b._fox_sprite_frame(100), 12)

    def test_ground_jump_and_canvas_balance(self):
        self.buddy.state = "listening"
        for right in (False, True):
            self.buddy.face_right = right
            for lift in (0, 26):
                self.buddy.pose["lift"] = lift
                canvas = SpriteCanvas()
                self.buddy.draw(canvas, now=100)
                self.assertEqual(canvas.depth, 0)
                frame, y, _, h = canvas.frames[0]
                self.assertAlmostEqual(y + h * module.FOX_SPRITE_GROUNDS[frame], 298 - lift)

    def test_vector_fallback_for_non_raster_canvas(self):
        self.assertFalse(module.Canvas().sprite("missing", 0, 4, 4, 0, 0, 10, 10))

    def test_sleep_curls_up_even_immediately_after_walking(self):
        b = self.buddy
        b.state = "idle"
        b.activity = {"name": "sleep"}
        b._stand_until = 200
        canvas = SpriteCanvas()
        b.draw(canvas, now=100)
        self.assertEqual(canvas.paths, ["red-white-fox-sleeping.png"])
        self.assertEqual(canvas.depth, 0)

    def test_idle_rest_curls_up_and_wakes_when_addressed_or_picked_up(self):
        b = self.buddy
        b.state = "idle"
        self.assertTrue(b._fox_curled_up(100))
        for state in ("listening", "thinking", "speaking"):
            b.state = state
            canvas = SpriteCanvas()
            b.draw(canvas, now=100)
            self.assertEqual(canvas.paths, ["red-white-serious-fox.png"])
        b.state = "idle"
        b.dragging = True
        self.assertFalse(b._fox_curled_up(100))

    def test_sleep_breathes_without_moving_its_floor_anchor(self):
        b = self.buddy
        b.state = "idle"
        first, second = SpriteCanvas(), SpriteCanvas()
        b.t = 0
        b.draw(first, now=100)
        b.t = 1
        b.draw(second, now=101)
        self.assertEqual(first.frames, second.frames)
        self.assertNotEqual(first.scales, second.scales)

    def test_sleep_command_waits_for_acknowledgement_then_wakes(self):
        b = self.buddy
        b.state = "thinking"
        b._start_activity("sleep")
        now = b.activity["start"]
        b.tick(now)
        b.state = "speaking"
        b.tick(now + 1)
        self.assertIsNotNone(b.activity)
        self.assertFalse(b._fox_curled_up(now + 1))
        b.state = "idle"
        b.tick(now + 2)
        self.assertTrue(b._fox_curled_up(now + 2))
        b.state = "listening"
        b.tick(now + 3)
        self.assertIsNone(b.activity)


if __name__ == "__main__":
    unittest.main()
