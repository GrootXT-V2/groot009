import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groot.buddy import Area, Buddy
from groot.gui import Session
from test_realistic_fox import SpriteCanvas


class CornerRoutineTests(unittest.TestCase):
    def setUp(self):
        self.buddy = Buddy(style="fox", area=Area(0, 25, 800, 600))
        self.buddy.caption = ""
        self.buddy.set_state("idle")
        self.now = time.monotonic()
        self.tick()
        self.said, self.asked = [], []
        self.heard = iter(())
        brain = SimpleNamespace(reply=self.answer)
        self.session = Session(
            brain, SimpleNamespace(say=self.said.append, stop=lambda: None),
            lambda timeout=None: next(self.heard, ""),
            self.buddy.set_state, self.buddy.set_text,
            on_stop=self.buddy.end_conversation)

    def answer(self, text):
        self.asked.append(text)
        return "Done."

    def tick(self, count=1):
        for _ in range(count):
            self.now += Buddy.FRAME
            self.buddy.tick(self.now)

    def arrive(self):
        for _ in range(2000):
            self.tick()
            if self.buddy._fox_curled_up(self.now):
                return
        self.fail("Fox never reached a sleeping corner")

    def canvas(self):
        self.buddy.caption = ""
        canvas = SpriteCanvas()
        self.buddy.draw(canvas, self.now)
        return canvas

    def test_startup_sleeps_in_corner_indefinitely_with_floating_zs(self):
        b = self.buddy
        position = (b.x, b.y)
        self.tick(3000)
        self.assertEqual((b.x, b.y), position)
        self.assertEqual(b.x, b._fox_corner_x("right"))
        self.assertEqual(self.canvas().texts, ["Z", "Z", "Z"])
        self.assertTrue(b._fox_curled_up(self.now))

    def test_hay_groot_questions_tasks_stop_walk_and_alternating_naps(self):
        self.heard = iter(["hay groot", "what time is it", "remember buy milk", "stop"])
        self.session._wake_word_turn()
        self.tick()
        self.assertTrue(self.session.active)
        self.assertFalse(self.buddy._fox_curled_up(self.now))
        start = self.buddy.x
        for _ in range(3):
            self.session._conversation_turn()
            self.tick()
        self.assertEqual(self.asked, ["what time is it", "remember buy milk"])
        self.assertEqual(self.buddy.x, start)
        self.session._conversation_turn()
        self.tick(5)
        self.assertFalse(self.session.active)
        self.assertLess(self.buddy.x, start)
        self.assertNotIn("Z", self.canvas().texts)
        self.arrive()
        self.assertEqual(self.buddy.x, self.buddy._fox_corner_x("left"))
        self.assertEqual(self.canvas().texts, ["Z", "Z", "Z"])
        self.session.start()
        self.tick()
        self.session.stop()
        self.tick()
        self.arrive()
        self.assertEqual(self.buddy.x, self.buddy._fox_corner_x("right"))

    def test_sitting_does_not_bounce_sway_or_change_body_during_speech(self):
        self.session.start()
        self.tick()
        position = self.buddy.x, self.buddy.y
        rectangles = []
        for state in ("listening", "thinking", "speaking"):
            self.buddy.set_state(state)
            self.tick(200)
            self.assertEqual((self.buddy.x, self.buddy.y), position)
            for key in ("bob", "lean", "lift"):
                self.assertEqual(self.buddy.pose[key], 0)
            canvas = self.canvas()
            rectangles.append(canvas.frames)
            self.assertEqual(canvas.scales, [])
            self.assertNotIn("Z", canvas.texts)  # awake emotion marks are allowed
        self.assertEqual(rectangles[0], rectangles[1])
        self.assertEqual(rectangles[1], rectangles[2])

    def test_wake_during_return_walk_stops_and_duplicate_stop_does_not_reverse(self):
        self.session.start()
        self.tick()
        self.session.stop()
        self.tick(20)
        destination = self.buddy._fox_destination
        self.session.stop()
        self.tick()
        self.assertEqual(self.buddy._fox_destination, destination)
        self.heard = iter(["hey groot"])
        self.session._wake_word_turn()
        self.tick()
        position = self.buddy.x
        self.tick(100)
        self.assertEqual(self.buddy.x, position)
        self.assertEqual(self.buddy._fox_mode, "awake")
        self.assertIsNone(self.buddy._fox_destination)
        self.assertNotIn("Z", self.canvas().texts)

    def test_drop_in_middle_walks_to_corner_before_sleeping(self):
        b = self.buddy
        b.press(b.x, b.y)
        b.drag(280, b.y - 100)
        b.release()
        self.assertFalse(b._fox_curled_up(self.now))
        self.arrive()
        self.assertIn(b.x, (b._fox_corner_x("left"), b._fox_corner_x("right")))
        self.assertEqual(b.y, b.floor)


if __name__ == "__main__":
    unittest.main()
