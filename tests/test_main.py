from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import main  # noqa: E402
from config import DEFAULT_CONFIG, load_config  # noqa: E402


class MainTests(unittest.TestCase):
    def make_config(self, root: Path):
        path = root / "settings.ini"
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        (root / "reference.png").write_bytes(b"placeholder")
        return load_config(path)

    def test_check_config_returns_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self.make_config(Path(directory))
            with contextlib.redirect_stdout(io.StringIO()):
                result = main.main(["--config", str(config.config_path), "--check-config"])
            self.assertEqual(result, 0)

    def test_keyboard_interrupt_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self.make_config(Path(directory))
            with patch("main.time.sleep", side_effect=KeyboardInterrupt):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = main.run_stage_two(config)
            self.assertEqual(result, 0)

    def test_single_scan_returns_one_when_not_matched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self.make_config(Path(directory))
            detector = SimpleNamespace(
                detect=lambda frame, origin: SimpleNamespace(
                    matched=False, confidence=0.5, left=10, top=20, width=30, height=40
                )
            )
            capture_type = type(
                "FakeCapture",
                (),
                {
                    "__enter__": lambda self: self,
                    "__exit__": lambda self, *args: None,
                    "grab": lambda self, monitor, region: (object(), (0, 0)),
                },
            )
            with patch("main.TemplateDetector", return_value=detector):
                with patch("main.ScreenCapture", return_value=capture_type()):
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = main.test_once(config)
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
