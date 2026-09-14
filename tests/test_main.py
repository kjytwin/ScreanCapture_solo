from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import main  # noqa: E402
from config import DEFAULT_CONFIG, load_config  # noqa: E402


class MainTests(unittest.TestCase):
    def test_check_config_returns_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "settings.ini"
            config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            reference = np.array([[0, 100], [200, 255]], dtype=np.uint8)
            (root / "reference.png").write_bytes(cv2.imencode(".png", reference)[1].tobytes())
            with patch("diagnostics.ScreenCapture") as capture, contextlib.redirect_stdout(io.StringIO()):
                capture.return_value.__enter__.return_value.grab.return_value = (reference, (0, 0))
                result = main.main(["--config", str(config_path), "--check-config"])
            self.assertEqual(result, 0)

    def test_keyboard_interrupt_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "settings.ini"
            config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            config = load_config(config_path)
            capture_type = type(
                "InterruptingCapture",
                (),
                {
                    "__enter__": lambda self: self,
                    "__exit__": lambda self, *args: None,
                    "grab": lambda self, monitor, region: (_ for _ in ()).throw(
                        KeyboardInterrupt()
                    ),
                },
            )
            output = io.StringIO()
            with patch("main.TemplateDetector", return_value=object()):
                with patch("main.ScreenCapture", return_value=capture_type()):
                    with contextlib.redirect_stdout(output):
                        result = main.run_watcher(config)
            self.assertEqual(result, 0)
            self.assertIn("안전하게 종료", output.getvalue())

    def test_file_cannot_be_used_as_log_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "settings.ini"
            config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            (root / "logs").write_text("not a directory", encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                result = main.main(["--config", str(config_path), "--check-config"])
            self.assertEqual(result, 2)
            self.assertIn("로그 경로가 폴더가 아닙니다", error.getvalue())

    def test_single_scan_returns_one_when_not_matched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "settings.ini"
            config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            config = load_config(config_path)
            detector = SimpleNamespace(
                detect=lambda frame, origin: SimpleNamespace(
                    matched=False,
                    confidence=0.5,
                    left=10,
                    top=20,
                    width=30,
                    height=40,
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

    def test_realtime_loop_reports_found_and_disappeared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "settings.ini"
            quiet_config = (
                DEFAULT_CONFIG.replace("sound = true", "sound = false")
                .replace("desktop_notification = true", "desktop_notification = false")
                .replace("save_capture = true", "save_capture = false")
            )
            config_path.write_text(quiet_config, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            config = load_config(config_path)
            main.prepare_directories(config)

            frames = iter([object() for _ in range(5)])
            matches = iter([True, True, False, False, False])

            class FakeCapture:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return None

                def grab(self, monitor, region):
                    try:
                        return next(frames), (0, 0)
                    except StopIteration as exc:
                        raise KeyboardInterrupt from exc

            def detect(frame, origin):
                matched = next(matches)
                return SimpleNamespace(
                    matched=matched,
                    confidence=0.99 if matched else 0.1,
                    left=10,
                    top=20,
                    width=30,
                    height=40,
                )

            output = io.StringIO()
            with patch("main.TemplateDetector", return_value=SimpleNamespace(detect=detect)):
                with patch("main.ScreenCapture", return_value=FakeCapture()):
                    with patch("main.time.sleep", return_value=None):
                        with contextlib.redirect_stdout(output):
                            result = main.run_watcher(config)

            self.assertEqual(result, 0)
            text = output.getvalue()
            self.assertEqual(text.count("이미지 발견"), 1)
            self.assertEqual(text.count("이미지 사라짐"), 1)
            self.assertIn("안전하게 종료", text)


if __name__ == "__main__":
    unittest.main()
