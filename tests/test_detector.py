from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import cv2
    import numpy as np
except ImportError:  # 설치 전에는 명시적으로 건너뛴다.
    cv2 = None
    np = None

from detector import DetectorError, TemplateDetector  # noqa: E402


@unittest.skipIf(cv2 is None or np is None, "OpenCV와 NumPy가 필요합니다.")
class DetectorTests(unittest.TestCase):
    def create_detector(self, root: Path, reference) -> TemplateDetector:
        path = root / "reference.png"
        self.assertTrue(cv2.imwrite(str(path), reference))
        return TemplateDetector(path, 0.95)

    def test_exact_template_is_found_at_absolute_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = np.array(
                [[0, 20, 40], [60, 255, 80], [100, 120, 140]], dtype=np.uint8
            )
            frame = np.zeros((20, 30), dtype=np.uint8)
            frame[7:10, 11:14] = reference
            detector = self.create_detector(root, reference)
            result = detector.detect(frame, origin=(100, 200))
            self.assertTrue(result.matched)
            self.assertGreaterEqual(result.confidence, 0.99)
            self.assertEqual((result.left, result.top), (111, 207))

    def test_reference_larger_than_frame_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = np.indices((10, 10)).sum(axis=0).astype(np.uint8) * 255
            detector = self.create_detector(root, reference)
            with self.assertRaisesRegex(DetectorError, "감시 영역"):
                detector.detect(np.zeros((5, 5), dtype=np.uint8))

    def test_constant_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(DetectorError, "명암 차이"):
                self.create_detector(root, np.zeros((10, 10), dtype=np.uint8))


if __name__ == "__main__":
    unittest.main()
