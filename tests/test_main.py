from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            (root / "reference.png").write_bytes(b"placeholder")
            with contextlib.redirect_stdout(io.StringIO()):
                result = main.main(["--config", str(config_path), "--check-config"])
            self.assertEqual(result, 0)

    def test_keyboard_interrupt_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "settings.ini"
            config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            config = load_config(config_path)
            with patch("main.time.sleep", side_effect=KeyboardInterrupt):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = main.run_stage_one(config)
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()

