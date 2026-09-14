from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import DEFAULT_CONFIG, load_config
from detector import DetectionResult, DetectorError
from event_logger import RecordResult
from watch_engine import EngineEventKind, WatchEngine


class ImmediateWorker:
    def __init__(self, warn):
        self.warn = warn

    def submit(self, action, *args):
        action(*args)
        return True

    def close(self):
        pass


class FakeLogger:
    def __init__(self, *args):
        self.events = []

    def cleanup_old_captures(self):
        return ()

    def record_found(self, result, frame, occurred_at, allowed):
        self.events.append("found")
        return RecordResult(None, ())

    def record_disappeared(self, occurred_at):
        self.events.append("disappeared")
        return RecordResult(None, ())

    def record_error(self, message):
        self.events.append("error")
        return ()


class QuietNotifier:
    def __init__(self, *args):
        pass

    def notify_found(self, confidence):
        return ()


class WatchEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        path = root / "settings.ini"
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        (root / "reference.png").write_bytes(b"placeholder")
        self.config = replace(
            load_config(path),
            sound=False,
            desktop_notification=False,
            save_capture=False,
            interval_ms=10,
        )

    def make_engine(self, capture_factory, detector, callback=None, waiter=None, **kwargs):
        return WatchEngine(
            self.config,
            callback,
            capture_factory=capture_factory,
            detector_factory=lambda *args: detector,
            logger_factory=FakeLogger,
            notifier_factory=QuietNotifier,
            worker_factory=ImmediateWorker,
            waiter=waiter or (lambda seconds: False),
            **kwargs,
        )

    def test_engine_reports_detection_sequence(self):
        frames = iter([1, 2, 3, 4, 5])
        engine = None

        class Capture:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def grab(self, *args):
                try:
                    return next(frames), (0, 0)
                except StopIteration:
                    engine.stop()
                    return 0, (0, 0)

        scores = {1: .9, 2: .9, 3: .1, 4: .1, 5: .1, 0: .1}
        detector = type("Detector", (), {"detect": lambda self, frame, origin:
            DetectionResult(scores[frame] >= .85, scores[frame], 1, 2, 3, 4)})()
        events = []
        engine = self.make_engine(Capture, detector, events.append)
        engine.run()
        kinds = [event.kind for event in events]
        self.assertEqual(kinds.count(EngineEventKind.FOUND), 1)
        self.assertEqual(kinds.count(EngineEventKind.DISAPPEARED), 1)
        self.assertEqual(kinds[0], EngineEventKind.STARTED)
        self.assertEqual(kinds[-1], EngineEventKind.STOPPED)

    def test_pause_resume_and_stop_are_thread_safe(self):
        scanned = threading.Event()
        release = threading.Event()

        class Capture:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def grab(self, *args):
                scanned.set()
                return 1, (0, 0)

        detector = type("Detector", (), {"detect": lambda self, frame, origin:
            DetectionResult(False, .1, 0, 0, 1, 1)})()
        events = []
        engine = self.make_engine(Capture, detector, events.append)
        thread = threading.Thread(target=engine.run)
        thread.start()
        self.assertTrue(scanned.wait(2))
        engine.pause()
        for _ in range(100):
            if any(event.kind is EngineEventKind.PAUSED for event in events):
                break
            threading.Event().wait(.01)
        self.assertTrue(engine.paused)
        engine.resume()
        engine.stop()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(engine.running)

    def test_initialization_failure_resets_running_state(self):
        def fail(*args):
            raise DetectorError("bad reference")

        engine = WatchEngine(self.config, detector_factory=fail)
        with self.assertRaises(DetectorError):
            engine.run()
        self.assertFalse(engine.running)

    def test_scan_events_are_opt_in_and_rate_limited(self):
        frames = iter(range(6))
        engine = None

        class Capture:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def grab(self, *args):
                try:
                    return next(frames), (0, 0)
                except StopIteration:
                    engine.stop()
                    return 0, (0, 0)

        detector = type("Detector", (), {"detect": lambda self, frame, origin:
            DetectionResult(False, .1, 0, 0, 1, 1)})()
        events = []
        clock = iter([0, 0, .1, .1, .2, .2, .3, .3, .4, .4, .5, .5, .6, .6, .7, .7])
        engine = WatchEngine(
            self.config,
            events.append,
            capture_factory=Capture,
            detector_factory=lambda *args: detector,
            logger_factory=FakeLogger,
            notifier_factory=QuietNotifier,
            worker_factory=ImmediateWorker,
            waiter=lambda seconds: False,
            monotonic=lambda: next(clock),
            emit_scan_events=True,
            scan_event_interval=.25,
        )
        engine.run()
        scan_events = [event for event in events if event.kind is EngineEventKind.SCAN]
        self.assertLess(len(scan_events), 6)
        self.assertGreaterEqual(len(scan_events), 2)

    def test_stop_before_run_prevents_first_capture(self):
        class Capture:
            def __init__(self):
                raise AssertionError("중단 후 캡처를 시작하면 안 됩니다.")

        detector = type("Detector", (), {})()
        events = []
        engine = self.make_engine(Capture, detector, events.append)
        engine.stop()
        engine.run()
        kinds = [event.kind for event in events]
        self.assertEqual(kinds, [EngineEventKind.STARTED, EngineEventKind.STOPPED])


if __name__ == "__main__":
    unittest.main()
