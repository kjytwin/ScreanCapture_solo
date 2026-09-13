"""감지 이벤트 로그, 스크린샷, 보존 기간을 관리한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import re

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
        max_capture_mb: int = 512,
        max_log_mb: int = 5,
        log_backups: int = 3,
    ) -> None:
        self.log_path = log_directory / "events.jsonl"
        self.capture_directory = capture_directory
        self.save_capture = save_capture
        self.retention_days = retention_days
        self.max_capture_bytes = max_capture_mb * 1024 * 1024
        self.max_log_bytes = max_log_mb * 1024 * 1024
        self.log_backups = log_backups

    def cleanup_old_captures(self, now: datetime | None = None) -> tuple[str, ...]:
        """생성 파일명에 해당하는 캡처에 기간·용량 제한을 적용한다."""
        current = now or datetime.now()
        cutoff = current - timedelta(days=self.retention_days)
        warnings: list[str] = []
        try:
            candidates = list(self.capture_directory.glob("detected_*.png"))
        except OSError as exc:
            return (f"캡처 파일 목록을 확인하지 못했습니다: {exc}",)
        remaining = []
        for path in candidates:
            if not re.fullmatch(r"detected_\d{8}_\d{6}_\d{6}\.png", path.name) or path.is_symlink():
                continue
            try:
                stat = path.stat()
                modified = datetime.fromtimestamp(stat.st_mtime, tz=current.tzinfo)
                if self.retention_days and modified < cutoff:
                    path.unlink()
                else:
                    remaining.append((stat.st_mtime, stat.st_size, path))
            except OSError as exc:
                warnings.append(f"오래된 캡처를 정리하지 못했습니다: {path} ({exc})")
        total = sum(size for _, size, _ in remaining)
        for _, size, path in sorted(remaining):
            if not self.max_capture_bytes or total <= self.max_capture_bytes:
                break
            try:
                path.unlink()
                total -= size
            except OSError as exc:
                warnings.append(f"용량 제한 캡처 정리 실패: {path} ({exc})")
        return tuple(warnings)

    def _append(self, payload: dict[str, Any]) -> str | None:
        try:
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            if (self.log_path.exists() and self.log_path.stat().st_size > 0
                    and self.log_path.stat().st_size + len(line.encode("utf-8")) > self.max_log_bytes):
                for index in range(self.log_backups, 0, -1):
                    source = self.log_path if index == 1 else Path(f"{self.log_path}.{index - 1}")
                    if source.exists():
                        source.replace(Path(f"{self.log_path}.{index}"))
            with self.log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(line)
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

    def record_error(self, message: str) -> tuple[str, ...]:
        warning = self._append({"time": datetime.now().astimezone().isoformat(),
                                "event": "capture_error", "message": message})
        return (warning,) if warning else ()
