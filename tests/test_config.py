from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import ConfigError, DEFAULT_CONFIG, ensure_config, load_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_missing_config_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            self.assertTrue(ensure_config(path))
            self.assertTrue(path.is_file())
            self.assertFalse(ensure_config(path))

    def test_default_config_loads_with_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.ini").write_text(DEFAULT_CONFIG, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            config = load_config(root / "settings.ini")
            self.assertEqual(config.monitor, 1)
            self.assertIsNone(config.region)
            self.assertEqual(config.confidence, 0.85)

    def test_invalid_confidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = DEFAULT_CONFIG.replace("confidence = 0.85", "confidence = 1.5")
            (root / "settings.ini").write_text(content, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            with self.assertRaisesRegex(ConfigError, "confidence"):
                load_config(root / "settings.ini")

    def test_invalid_region_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = DEFAULT_CONFIG.replace("region = full", "region = 1,2,0,4")
            (root / "settings.ini").write_text(content, encoding="utf-8")
            (root / "reference.png").write_bytes(b"placeholder")
            with self.assertRaisesRegex(ConfigError, "width"):
                load_config(root / "settings.ini")

    def test_missing_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.ini").write_text(DEFAULT_CONFIG, encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "기준 이미지"):
                load_config(root / "settings.ini")


if __name__ == "__main__":
    unittest.main()

