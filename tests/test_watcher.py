from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from watcher import DetectionState, EventKind  # noqa: E402


class DetectionStateTests(unittest.TestCase):
    def test_found_requires_consecutive_matches(self) -> None:
        state = DetectionState(consecutive_matches=2, cooldown_seconds=3)
        self.assertIsNone(state.update(True, 0.0))
        event = state.update(True, 0.1)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.FOUND)
        self.assertTrue(state.present)

    def test_intermittent_match_does_not_trigger_found(self) -> None:
        state = DetectionState(consecutive_matches=2, cooldown_seconds=3)
        self.assertIsNone(state.update(True, 0.0))
        self.assertIsNone(state.update(False, 0.1))
        self.assertIsNone(state.update(True, 0.2))
        self.assertFalse(state.present)

    def test_disappearance_requires_consecutive_misses(self) -> None:
        state = DetectionState(consecutive_matches=2, cooldown_seconds=3)
        state.update(True, 0.0)
        state.update(True, 0.1)
        self.assertIsNone(state.update(False, 0.2))
        event = state.update(False, 0.3)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, EventKind.DISAPPEARED)
        self.assertFalse(state.present)

    def test_single_miss_does_not_lose_present_state(self) -> None:
        state = DetectionState(consecutive_matches=2, cooldown_seconds=3)
        state.update(True, 0.0)
        state.update(True, 0.1)
        state.update(False, 0.2)
        self.assertIsNone(state.update(True, 0.3))
        self.assertTrue(state.present)

    def test_reappearance_inside_cooldown_suppresses_notification(self) -> None:
        state = DetectionState(consecutive_matches=1, cooldown_seconds=3)
        first = state.update(True, 0.0)
        state.update(False, 0.1)
        second = state.update(True, 1.0)
        self.assertTrue(first.notification_allowed)
        self.assertFalse(second.notification_allowed)

    def test_reappearance_after_cooldown_allows_notification(self) -> None:
        state = DetectionState(consecutive_matches=1, cooldown_seconds=3)
        state.update(True, 0.0)
        state.update(False, 0.1)
        event = state.update(True, 3.0)
        self.assertTrue(event.notification_allowed)


if __name__ == "__main__":
    unittest.main()
