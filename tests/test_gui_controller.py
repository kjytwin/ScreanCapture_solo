from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import ConfigError, DEFAULT_CONFIG, load_config, save_config
from detector import DetectionResult
from gui_controller import GuiController, config_from_form, parse_region
from watch_engine import EngineEvent, EngineEventKind


class FakeEngine:
    def __init__(self, config, callback, **kwargs):
        self.callback = callback
        self.paused = False
        self.stopped = threading.Event()

    def run(self):
        self.callback(EngineEvent(EngineEventKind.STARTED, datetime.now().astimezone()))
        self.stopped.wait(2)
        self.callback(EngineEvent(EngineEventKind.STOPPED, datetime.now().astimezone()))

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped.set()


class GuiControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "settings.ini"
        self.path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        (self.root / "reference.png").write_bytes(b"placeholder")
        self.config = load_config(self.path)

    def form(self, **overrides):
        values = {
            "reference": str(self.config.reference),
            "monitor": "1",
            "region": "full",
            "confidence": "0.85",
            "disappearance_confidence": "0.80",
            "interval_ms": "100",
            "consecutive_matches": "2",
            "consecutive_misses": "3",
            "cooldown_seconds": "3",
            "sound": True,
            "desktop_notification": True,
            "save_capture": True,
            "retention_days": "7",
            "max_capture_mb": "512",
        }
        values.update(overrides)
        return values

    def test_form_values_build_valid_config(self):
        config = config_from_form(
            self.config,
            self.form(region="10,20,300,200", interval_ms="150", sound=False),
        )
        self.assertEqual(str(config.region), "10,20,300,200")
        self.assertEqual(config.interval_ms, 150)
        self.assertFalse(config.sound)

    def test_text_boolean_false_is_not_treated_as_true(self):
        config = config_from_form(
            self.config,
            self.form(sound="false", desktop_notification="0", save_capture="off"),
        )
        self.assertFalse(config.sound)
        self.assertFalse(config.desktop_notification)
        self.assertFalse(config.save_capture)

    def test_bad_form_values_are_rejected(self):
        for values in (
            self.form(region="1,2,3"),
            self.form(confidence="abc"),
            self.form(confidence="0.7", disappearance_confidence="0.8"),
        ):
            with self.subTest(values=values), self.assertRaises(ConfigError):
                config_from_form(self.config, values)

    def test_region_rejects_negative_relative_coordinates(self):
        with self.assertRaises(ConfigError):
            parse_region("-1,0,100,100")

    def test_save_config_round_trip_keeps_values(self):
        changed = config_from_form(
            self.config,
            self.form(region="1,2,30,40", confidence="0.9", sound=False),
        )
        save_config(changed)
        loaded = load_config(self.path)
        self.assertEqual(loaded, changed)

    def test_controller_start_pause_resume_stop(self):
        controller = GuiController(self.config, engine_factory=FakeEngine)
        controller.start(self.config)
        for _ in range(100):
            if controller.active:
                break
            threading.Event().wait(.01)
        self.assertTrue(controller.active)
        controller.pause_or_resume()
        self.assertTrue(controller.paused)
        controller.pause_or_resume()
        self.assertFalse(controller.paused)
        self.assertTrue(controller.stop())
        kinds = [event.kind for event in controller.drain_events()]
        self.assertIn(EngineEventKind.STARTED, kinds)
        self.assertIn(EngineEventKind.STOPPED, kinds)

    def test_scan_events_are_coalesced(self):
        controller = GuiController(self.config)
        for score in (.1, .2, .3):
            controller._receive(
                EngineEvent(
                    EngineEventKind.SCAN,
                    datetime.now().astimezone(),
                    result=DetectionResult(False, score, 0, 0, 1, 1),
                )
            )
        events = controller.drain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].result.confidence, .3)


if __name__ == "__main__":
    unittest.main()
