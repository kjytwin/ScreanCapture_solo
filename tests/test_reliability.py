from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main
from capture import CaptureError
from config import DEFAULT_CONFIG, ConfigError, load_config
from detector import DetectionResult, save_detection_preview
from event_logger import EventLogger
from watcher import DetectionState, EventKind
from worker import ActionWorker


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "settings.ini"
        self.path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        self.reference = np.array([[0, 80], [160, 255]], dtype=np.uint8)
        (self.root / "reference.png").write_bytes(cv2.imencode(".png", self.reference)[1].tobytes())
        self.config = replace(load_config(self.path), sound=False, desktop_notification=False,
                              save_capture=False)
        main.prepare_directories(self.config)

    def test_corrupt_reference_rejected_before_capture(self):
        self.config.reference.write_bytes(b"broken png")
        with patch("main.ScreenCapture") as capture, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main.main(["--config", str(self.path), "--check-config"]), 3)
        capture.assert_not_called()

    def test_invalid_monitor_fails_check(self):
        with patch("main.ScreenCapture") as capture:
            capture.return_value.__enter__.return_value.grab.side_effect = CaptureError("invalid monitor")
            with self.assertRaises(CaptureError):
                main.validate_environment(self.config)

    def test_unwritable_storage_fails_validation(self):
        with patch("main.tempfile.TemporaryFile", side_effect=PermissionError("denied")):
            with self.assertRaises(ConfigError):
                main.prepare_directories(self.config)

    def test_legacy_config_keeps_original_threshold_and_counts(self):
        content = DEFAULT_CONFIG.replace("disappearance_confidence = 0.80\n", "").replace("consecutive_misses = 3\n", "")
        self.path.write_text(content, encoding="utf-8")
        config = load_config(self.path)
        self.assertEqual(config.disappearance_confidence, config.confidence)
        self.assertEqual(config.consecutive_misses, config.consecutive_matches)

    def test_invalid_new_settings_rejected(self):
        for setting, invalid in [("disappearance_confidence = 0.80", "disappearance_confidence = 0.95"),
                                 ("consecutive_misses = 3", "consecutive_misses = 0")]:
            with self.subTest(setting=setting):
                self.path.write_text(DEFAULT_CONFIG.replace(setting, invalid), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(self.path)

    def test_preview_uses_relative_coordinates_without_mutating_frame(self):
        frame = np.zeros((60, 60, 3), dtype=np.uint8)
        result = DetectionResult(True, 0.95, -90, 120, 10, 10)
        output = self.root / "한글" / "검사.png"
        save_detection_preview(frame, result, (-100, 100), output)
        image = cv2.imdecode(np.frombuffer(output.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(tuple(image[20, 10]), (0, 200, 0))
        self.assertEqual(int(frame.sum()), 0)

    def test_independent_misses_and_failed_observation_break_streak(self):
        state = DetectionState(2, 0, 3)
        state.update(True, 0)
        state.reset_pending()
        self.assertIsNone(state.update(True, 1))
        self.assertEqual(state.update(True, 2).kind, EventKind.FOUND)
        state.update(False, 3)
        state.reset_pending()
        self.assertTrue(state.present)
        self.assertIsNone(state.update(False, 4))
        self.assertIsNone(state.update(False, 5))
        self.assertEqual(state.update(False, 6).kind, EventKind.DISAPPEARED)

    def run_scores(self, scores):
        values = iter(scores)
        class Capture:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def grab(self, *args):
                try: return next(values), (0, 0)
                except StopIteration: raise KeyboardInterrupt
        detector = SimpleNamespace(detect=lambda score, origin: DetectionResult(score >= .85, score, 0, 0, 2, 2))
        with patch("main.ScreenCapture", Capture), patch("main.TemplateDetector", return_value=detector), patch("main.time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            main.run_watcher(self.config)
        return [json.loads(line)["event"] for line in (self.config.log_directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_threshold_hysteresis_avoids_repeated_found_events(self):
        self.assertEqual(self.run_scores([.90, .90, .82, .84, .81, .79, .79, .79]), ["found", "disappeared"])

    def test_cleanup_runs_again_after_one_hour(self):
        with patch("main.time.monotonic", side_effect=[0, 3601, 3601, 3602, 3602]), patch.object(EventLogger, "cleanup_old_captures", return_value=()) as cleanup:
            self.run_scores([.9, .9])
        # Startup, hourly maintenance, and the found event each request cleanup.
        self.assertEqual(cleanup.call_count, 3)

    def test_capture_retry_is_bounded_and_logged(self):
        with patch("main.ScreenCapture", side_effect=CaptureError("offline")) as capture, patch("main.TemplateDetector"), patch("main.time.sleep"), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(CaptureError, "3회"):
                main.run_watcher(self.config)
        self.assertEqual(capture.call_count, 3)
        events = (self.config.log_directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(events), 3)

    def test_capture_recovers_after_transient_initialization_error(self):
        class Capture:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def grab(self, *args): raise KeyboardInterrupt
        with patch("main.ScreenCapture", side_effect=[CaptureError("offline"), Capture()]) as capture, patch("main.TemplateDetector"), patch("main.time.sleep"), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main.run_watcher(self.config), 0)
        self.assertEqual(capture.call_count, 2)

    def test_log_rotation_preserves_valid_json_and_limits_backups(self):
        logger = EventLogger(self.config.log_directory, self.config.capture_directory, False, 7)
        logger.max_log_bytes = 150
        for _ in range(20):
            self.assertEqual(logger.record_disappeared().warnings, ())
        logs = list(self.config.log_directory.glob("events.jsonl*"))
        self.assertEqual(len(logs), 4)
        for path in logs:
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertEqual(json.loads(line)["event"], "disappeared")

    def test_capture_quota_preserves_unrelated_files(self):
        logger = EventLogger(self.config.log_directory, self.config.capture_directory, False, 0)
        logger.max_capture_bytes = 15
        old = self.config.capture_directory / "detected_20260101_000000_000000.png"
        new = self.config.capture_directory / "detected_20260102_000000_000000.png"
        unrelated = self.config.capture_directory / "detected_custom.png"
        for index, path in enumerate([old, new, unrelated]):
            path.write_bytes(b"x" * 10)
            os.utime(path, (100 + index, 100 + index))
        self.assertEqual(logger.cleanup_old_captures(), ())
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertTrue(unrelated.exists())

    def test_timezone_aware_cleanup(self):
        logger = EventLogger(self.config.log_directory, self.config.capture_directory, False, 7)
        old = self.config.capture_directory / "detected_20260101_000000_000000.png"
        old.write_bytes(b"x")
        now = datetime.now(timezone.utc)
        timestamp = (now - timedelta(days=8)).timestamp()
        os.utime(old, (timestamp, timestamp))
        self.assertEqual(logger.cleanup_old_captures(now), ())
        self.assertFalse(old.exists())


class WorkerTests(unittest.TestCase):
    def test_shutdown_timeout_reports_unfinished_work(self):
        entered, release = Event(), Event()
        warnings = []
        worker = ActionWorker(warnings.extend)
        def slow():
            entered.set()
            release.wait(3)
        worker.submit(slow)
        try:
            self.assertTrue(entered.wait(2))
            worker.close(timeout=0)
            self.assertTrue(any("미완료" in warning for warning in warnings))
        finally:
            release.set()
            worker.close()

    def test_slow_action_does_not_block_producer_and_queue_is_bounded(self):
        entered, release = Event(), Event()
        warnings, completed = [], []
        worker = ActionWorker(warnings.extend, capacity=1)
        def slow():
            entered.set()
            release.wait(3)
        try:
            self.assertTrue(worker.submit(slow))
            self.assertTrue(entered.wait(2))
            self.assertTrue(worker.submit(completed.append, 1))
            self.assertFalse(worker.submit(completed.append, 2))
        finally:
            release.set()
            worker.close()
        self.assertEqual(completed, [1])
        self.assertTrue(warnings)

    def test_action_exception_does_not_stop_following_work(self):
        warnings, completed = [], []
        worker = ActionWorker(warnings.extend)
        def fail(): raise OSError("disk full")
        worker.submit(fail)
        worker.submit(completed.append, 1)
        worker.close()
        self.assertEqual(completed, [1])
        self.assertIn("disk full", warnings[0])


if __name__ == "__main__":
    unittest.main()
