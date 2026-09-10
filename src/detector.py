"""OpenCV 템플릿 매칭 기반 이미지 탐지."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class DetectorError(RuntimeError):
    """기준 이미지 로드 또는 탐지를 수행할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class DetectionResult:
    matched: bool
    confidence: float
    left: int
    top: int
    width: int
    height: int


class TemplateDetector:
    def __init__(self, reference_path: Path, threshold: float) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise DetectorError(
                "이미지 분석 패키지가 없습니다. pip install -r requirements.txt를 실행하세요."
            ) from exc
        self._cv2 = cv2
        self.threshold = threshold
        try:
            # imread는 Windows 한글 경로에서 경고 후 실패할 수 있어 바이트로 읽는다.
            import numpy

            raw = numpy.fromfile(reference_path, dtype=numpy.uint8)
            encoded = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        except (OSError, ValueError, cv2.error) as exc:
            raise DetectorError(f"기준 이미지를 읽을 수 없습니다: {reference_path}") from exc
        if encoded is None or encoded.size == 0:
            raise DetectorError(f"올바른 기준 이미지가 아닙니다: {reference_path}")
        if float(encoded.std()) < 1e-6:
            raise DetectorError("기준 이미지에 구분 가능한 무늬나 명암 차이가 없습니다.")
        self._reference = encoded
        self.height, self.width = encoded.shape[:2]

    def detect(self, frame, origin: tuple[int, int] = (0, 0)) -> DetectionResult:
        if frame is None or getattr(frame, "size", 0) == 0:
            raise DetectorError("캡처 이미지가 비어 있습니다.")
        if len(frame.shape) == 3:
            gray = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
        elif len(frame.shape) == 2:
            gray = frame
        else:
            raise DetectorError("지원하지 않는 캡처 이미지 형식입니다.")

        frame_height, frame_width = gray.shape[:2]
        if self.width > frame_width or self.height > frame_height:
            raise DetectorError(
                f"기준 이미지({self.width}x{self.height})가 감시 영역"
                f"({frame_width}x{frame_height})보다 큽니다."
            )

        try:
            scores = self._cv2.matchTemplate(
                gray, self._reference, self._cv2.TM_CCOEFF_NORMED
            )
            _, maximum, _, location = self._cv2.minMaxLoc(scores)
        except self._cv2.error as exc:
            raise DetectorError(f"이미지 비교에 실패했습니다: {exc}") from exc
        confidence = max(0.0, min(1.0, float(maximum)))
        left = origin[0] + int(location[0])
        top = origin[1] + int(location[1])
        return DetectionResult(
            matched=confidence >= self.threshold,
            confidence=confidence,
            left=left,
            top=top,
            width=self.width,
            height=self.height,
        )
