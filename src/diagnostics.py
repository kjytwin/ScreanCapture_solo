"""CMD와 GUI가 공유하는 실행 전 환경 검사."""

from __future__ import annotations

import tempfile

from capture import ScreenCapture
from config import AppConfig, ConfigError
from detector import TemplateDetector


def prepare_directories(config: AppConfig) -> None:
    for label, directory in (
        ("로그", config.log_directory),
        ("캡처", config.capture_directory),
    ):
        if directory.exists() and not directory.is_dir():
            raise ConfigError(f"{label} 경로가 폴더가 아닙니다: {directory}")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b"ImageWatcher storage check")
                probe.flush()
        except OSError as exc:
            raise ConfigError(
                f"{label} 폴더를 준비하거나 쓸 수 없습니다: {directory} ({exc})"
            ) from exc


def validate_environment(config: AppConfig) -> None:
    """이미지 디코딩과 실제 모니터 캡처·비교까지 확인한다."""
    detector = TemplateDetector(config.reference, config.confidence)
    with ScreenCapture() as capture:
        frame, origin = capture.grab(config.monitor, config.region)
    detector.detect(frame, origin)
