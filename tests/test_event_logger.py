from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np  # noqa: E402

from detector import DetectionResult  # noqa: E402
from event_logger import EventLogger  # noqa: E402


class EventLoggerTests(unittest.TestCase):
    def create_logger(self, root: Path, **overrides) -> EventLogger:
        logs = root / "logs"
        captures = root / "captures"
        logs.mkdir()
        captures.mkdir()
        return EventLogger(
            logs,
            captures,
            overrides.get("save_capture", True),
            overrides.get("retention_days", 7),
        )

    def test_found_event_writes_json_and_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = self.create_logger(root)
            result = DetectionResult(True, 0.9876543, 10, 20, 30, 40)
            frame = np.zeros((50, 60, 3), dtype=np.uint8)
            recorded = logger.record_found(
                result, frame, datetime(2026, 9, 10, 12, 30, 0)
            )
            self.assertEqual(recorded.warnings, ())
            self.assertTrue(recorded.capture_path.is_file())
            payload = json.loads(logger.log_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["event"], "found")
            self.assertEqual(payload["confidence"], 0.987654)
            self.assertEqual((payload["left"], payload["top"]), (10, 20))

    def test_disappeared_event_does_not_write_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = self.create_logger(root)
            recorded = logger.record_disappeared(datetime(2026, 9, 10, 12, 31, 0))
            self.assertIsNone(recorded.capture_path)
            payload = json.loads(logger.log_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["event"], "disappeared")
            self.assertEqual(list((root / "captures").glob("*.png")), [])

    def test_capture_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = self.create_logger(root, save_capture=False)
            result = DetectionResult(True, 0.9, 0, 0, 10, 10)
            recorded = logger.record_found(result, object())
            self.assertIsNone(recorded.capture_path)
            self.assertEqual(recorded.warnings, ())

    def test_old_generated_captures_are_removed_only_after_retention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = self.create_logger(root, retention_days=7)
            old = root / "captures" / "detected_20200101_000000_000000.png"
            recent = root / "captures" / "detected_recent.png"
            unrelated = root / "captures" / "keep.png"
            for path in (old, recent, unrelated):
                path.write_bytes(b"x")
            now = datetime(2026, 9, 10, 12, 0, 0)
            old_time = (now - timedelta(days=8)).timestamp()
            recent_time = (now - timedelta(days=1)).timestamp()
            os.utime(old, (old_time, old_time))
            os.utime(recent, (recent_time, recent_time))
            os.utime(unrelated, (old_time, old_time))

            self.assertEqual(logger.cleanup_old_captures(now), ())
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(unrelated.exists())

    def test_log_failure_is_returned_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = self.create_logger(root, save_capture=False)
            logger.log_path = root / "missing" / "events.jsonl"
            result = DetectionResult(True, 0.9, 0, 0, 10, 10)
            recorded = logger.record_found(result, object())
            self.assertEqual(len(recorded.warnings), 1)
            self.assertIn("로그를 저장하지 못했습니다", recorded.warnings[0])


if __name__ == "__main__":
    unittest.main()
