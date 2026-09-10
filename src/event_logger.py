"""감지 이벤트 로그, 스크린샷, 보존 기간을 관리한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from detector import DetectionResult


@dataclass(frozen=True)
class RecordResult:
    capture_path: Path | None
    warnings: tuple[str, ...]


class EventLogger:
    def __init__(
        self,
        log_directory: Path,
        capture_directory: Path,
        save_capture: bool,
        retention_days: int,
    ) -> None:
        self.log_path = log_directory / "events.jsonl"
        self.capture_directory = capture_directory
        self.save_capture = save_capture
        self.retention_days = retention_days

    def cleanup_old_captures(self, now: datetime | None = None) -> tuple[str, ...]:
        """보존 기간을 넘긴 자체 생성 스크린샷만 제거한다. 0이면 정리하지 않는다."""
        if self.retention_days == 0:
            return ()
        current = now or datetime.now()
        cutoff = current - timedelta(days=self.retention_days)
        warnings: list[str] = []
        try:
            candidates = list(self.capture_directory.glob("detected_*.png"))
        except OSError as exc:
            return (f"캡처 파일 목록을 확인하지 못했습니다: {exc}",)
        for path in candidates:
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime)
                if modified < cutoff:
                    path.unlink()
            except OSError as exc:
                warnings.append(f"오래된 캡처를 정리하지 못했습니다: {path} ({exc})")
        return tuple(warnings)

    def _append(self, payload: dict[str, Any]) -> str | None:
        try:
            with self.log_path.open("a", encoding="utf-8") as log_file:
                json.dump(payload, log_file, ensure_ascii=False, separators=(",", ":"))
                log_file.write("\n")
        except (OSError, TypeError, ValueError) as exc:
            return f"이벤트 로그를 저장하지 못했습니다: {exc}"
        return None

    def _save_frame(self, frame, occurred_at: datetime) -> tuple[Path | None, str | None]:
        try:
            import cv2

            success, encoded = cv2.imencode(".png", frame)
            if not success:
                return None, "감지 화면을 PNG로 변환하지 못했습니다."
            name = occurred_at.strftime("detected_%Y%m%d_%H%M%S_%f.png")
            path = self.capture_directory / name
            path.write_bytes(encoded.tobytes())
            return path, None
        except Exception as exc:
            # OpenCV와 파일 시스템의 환경별 저장 예외를 감시 루프에서 격리한다.
            return None, f"감지 화면을 저장하지 못했습니다: {exc}"

    def record_found(
        self,
        result: DetectionResult,
        frame,
        occurred_at: datetime | None = None,
        notification_allowed: bool = True,
    ) -> RecordResult:
        timestamp = occurred_at or datetime.now().astimezone()
        warnings: list[str] = []
        capture_path: Path | None = None
        if self.save_capture:
            capture_path, warning = self._save_frame(frame, timestamp)
            if warning:
                warnings.append(warning)
        log_warning = self._append(
            {
                "time": timestamp.isoformat(timespec="milliseconds"),
                "event": "found",
                "confidence": round(result.confidence, 6),
                "left": result.left,
                "top": result.top,
                "width": result.width,
                "height": result.height,
                "capture": str(capture_path) if capture_path else None,
                "notification_allowed": notification_allowed,
            }
        )
        if log_warning:
            warnings.append(log_warning)
        return RecordResult(capture_path, tuple(warnings))

    def record_disappeared(self, occurred_at: datetime | None = None) -> RecordResult:
        timestamp = occurred_at or datetime.now().astimezone()
        warning = self._append(
            {
                "time": timestamp.isoformat(timespec="milliseconds"),
                "event": "disappeared",
            }
        )
        return RecordResult(None, (warning,) if warning else ())
