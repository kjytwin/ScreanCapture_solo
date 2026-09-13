from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from capture import CaptureError, ScreenCapture  # noqa: E402
from config import Region  # noqa: E402


class FakeSession:
    monitors = [
        {"left": -1280, "top": 0, "width": 3200, "height": 1080},
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -1280, "top": 0, "width": 1280, "height": 1024},
    ]


class CaptureTests(unittest.TestCase):
    def create_capture(self) -> ScreenCapture:
        capture = ScreenCapture.__new__(ScreenCapture)
        capture._session = FakeSession()
        return capture

    def test_full_monitor_area_uses_absolute_desktop_coordinates(self) -> None:
        area = self.create_capture()._capture_area(2, None)
        self.assertEqual(
            area, {"left": -1280, "top": 0, "width": 1280, "height": 1024}
        )

    def test_relative_region_is_converted_to_absolute_coordinates(self) -> None:
        area = self.create_capture()._capture_area(2, Region(10, 20, 300, 200))
        self.assertEqual(
            area, {"left": -1270, "top": 20, "width": 300, "height": 200}
        )

    def test_region_outside_monitor_is_rejected(self) -> None:
        with self.assertRaisesRegex(CaptureError, "범위를 벗어났습니다"):
            self.create_capture()._capture_area(1, Region(1800, 0, 200, 100))

    def test_unknown_monitor_is_rejected(self) -> None:
        with self.assertRaisesRegex(CaptureError, "사용 가능한 모니터 수: 2"):
            self.create_capture()._capture_area(3, None)

    def test_monitor_enumeration_failure_is_wrapped_for_retry(self) -> None:
        class OfflineSession:
            @property
            def monitors(self):
                raise RuntimeError("display disconnected")
        capture = self.create_capture()
        capture._session = OfflineSession()
        with self.assertRaisesRegex(CaptureError, "display disconnected"):
            capture.grab(1)


if __name__ == "__main__":
    unittest.main()
