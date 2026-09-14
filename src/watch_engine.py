"""CMD와 GUI가 함께 사용하는 화면 감시 엔진."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

from capture import CaptureError, ScreenCapture
from config import AppConfig
from detector import DetectionResult, TemplateDetector
from event_logger import EventLogger
from notifier import Notifier
from watcher import DetectionState, EventKind
from worker import ActionWorker


class EngineEventKind(str, Enum):
    STARTED = "started"
    PAUSED = "paused"
    RESUMED = "resumed"
    STOPPED = "stopped"
    SCAN = "scan"
    FOUND = "found"
    DISAPPEARED = "disappeared"
    CAPTURE_SAVED = "capture_saved"
    WARNING = "warning"
    ERROR = "error"
    PERFORMANCE = "performance"


@dataclass(frozen=True)
class EngineEvent:
    kind: EngineEventKind
    occurred_at: datetime
    message: str = ""
    result: DetectionResult | None = None
    capture_path: Path | None = None
    scans_per_second: float | None = None
    average_processing_ms: float | None = None


EventCallback = Callable[[EngineEvent], None]


class WatchEngine:
    """호출 스레드에서 감시를 실행하고 제어 명령은 스레드 안전하게 받는다."""

    def __init__(
        self,
        config: AppConfig,
        callback: EventCallback | None = None,
        *,
        capture_factory=None,
        detector_factory=None,
        logger_factory=None,
        notifier_factory=None,
        worker_factory=None,
        monotonic=None,
        perf_counter=None,
        waiter=None,
        emit_scan_events: bool = False,
        scan_event_interval: float = 0.25,
    ) -> None:
        self.config = config
        self._callback = callback or (lambda event: None)
        self._capture_factory = capture_factory or ScreenCapture
        self._detector_factory = detector_factory or TemplateDetector
        self._logger_factory = logger_factory or EventLogger
        self._notifier_factory = notifier_factory or Notifier
        self._worker_factory = worker_factory or ActionWorker
        self._monotonic = monotonic or time.monotonic
        self._perf_counter = perf_counter or time.perf_counter
        self._waiter = waiter
        self._emit_scan_events = emit_scan_events
        self._scan_event_interval = max(0.05, scan_event_interval)
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._state_lock = threading.Lock()
        self._running = False

    @property
    def running(self) -> bool:
        with self._state_lock:
            return self._running

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()

    def pause(self) -> None:
        if self.running:
            self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def _emit(self, kind: EngineEventKind, **values) -> None:
        event = EngineEvent(kind=kind, occurred_at=datetime.now().astimezone(), **values)
        try:
            self._callback(event)
        except Exception:
            # 화면 출력 콜백 오류가 감시를 중단시키지 않게 격리한다.
            pass

    def _wait(self, seconds: float) -> bool:
        """중단 요청에 즉시 반응하는 대기. 중단되면 True를 반환한다."""
        if self._waiter is not None:
            return bool(self._waiter(max(0.0, seconds)))
        return self._stop_event.wait(max(0.0, seconds))

    def run(self) -> None:
        with self._state_lock:
            if self._running:
                raise RuntimeError("감시 엔진이 이미 실행 중입니다.")
            self._running = True
        config = self.config
        capture = None
        worker = None
        try:
            detector = self._detector_factory(config.reference, config.confidence)
            state = DetectionState(
                config.consecutive_matches,
                config.cooldown_seconds,
                config.consecutive_misses,
            )
            event_logger = self._logger_factory(
                config.log_directory,
                config.capture_directory,
                config.save_capture,
                config.retention_days,
                config.max_capture_mb,
                config.max_log_mb,
                config.log_backups,
            )
            notifier = self._notifier_factory(config.sound, config.desktop_notification)

            def warn(warnings: tuple[str, ...]) -> None:
                for warning in warnings:
                    self._emit(EngineEventKind.WARNING, message=warning)

            worker = self._worker_factory(warn)

            def cleanup() -> None:
                warn(event_logger.cleanup_old_captures())

            def found(result, frame, occurred_at, allowed) -> None:
                recorded = event_logger.record_found(result, frame, occurred_at, allowed)
                warn(recorded.warnings)
                if recorded.capture_path:
                    self._emit(
                        EngineEventKind.CAPTURE_SAVED,
                        message=str(recorded.capture_path),
                        capture_path=recorded.capture_path,
                    )
                if allowed:
                    warn(notifier.notify_found(result.confidence))
                cleanup()

            def disappeared(occurred_at) -> None:
                warn(event_logger.record_disappeared(occurred_at).warnings)

            def capture_error(message) -> None:
                warn(event_logger.record_error(message))

            worker.submit(cleanup)
            failures = 0
            next_cleanup = self._monotonic() + 3600
            stats_started = self._perf_counter()
            cycles = 0
            busy_seconds = 0.0
            pause_reported = False
            next_scan_event = 0.0
            self._emit(EngineEventKind.STARTED)
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    if not pause_reported:
                        state.reset_pending()
                        self._emit(EngineEventKind.PAUSED)
                        pause_reported = True
                    self._wait(0.1)
                    continue
                if pause_reported:
                    self._emit(EngineEventKind.RESUMED)
                    pause_reported = False

                cycle_started = self._perf_counter()
                try:
                    if capture is None:
                        capture = self._capture_factory()
                        capture.__enter__()
                    frame, origin = capture.grab(config.monitor, config.region)
                except CaptureError as exc:
                    failures += 1
                    state.reset_pending()
                    message = f"화면 캡처 실패 {failures}/3: {exc}"
                    self._emit(EngineEventKind.WARNING, message=message)
                    worker.submit(capture_error, message)
                    if capture is not None:
                        capture.__exit__(None, None, None)
                        capture = None
                    if failures >= 3:
                        final_message = (
                            "화면 캡처가 연속 3회 실패했습니다. "
                            "화면 세션과 모니터 설정을 확인하세요."
                        )
                        raise CaptureError(final_message) from exc
                    if self._wait(float(failures)):
                        break
                    continue

                failures = 0
                result = detector.detect(frame, origin)
                threshold = (
                    config.disappearance_confidence if state.present else config.confidence
                )
                if threshold is None:
                    threshold = config.confidence
                observed_at = self._monotonic()
                event = state.update(result.confidence >= threshold, observed_at)
                if self._emit_scan_events and observed_at >= next_scan_event:
                    self._emit(EngineEventKind.SCAN, result=result)
                    next_scan_event = observed_at + self._scan_event_interval

                if event is not None and event.kind is EventKind.FOUND:
                    occurred_at = datetime.now().astimezone()
                    self._emit(EngineEventKind.FOUND, result=result)
                    worker.submit(
                        found,
                        result,
                        frame if config.save_capture else None,
                        occurred_at,
                        event.notification_allowed,
                    )
                elif event is not None and event.kind is EventKind.DISAPPEARED:
                    occurred_at = datetime.now().astimezone()
                    self._emit(EngineEventKind.DISAPPEARED, result=result)
                    worker.submit(disappeared, occurred_at)

                now = self._monotonic()
                if now >= next_cleanup and worker.submit(cleanup):
                    next_cleanup = now + 3600

                elapsed = self._perf_counter() - cycle_started
                cycles += 1
                busy_seconds += elapsed
                stats_elapsed = self._perf_counter() - stats_started
                if stats_elapsed >= 60:
                    self._emit(
                        EngineEventKind.PERFORMANCE,
                        scans_per_second=cycles / stats_elapsed,
                        average_processing_ms=busy_seconds / cycles * 1000,
                    )
                    stats_started = self._perf_counter()
                    cycles = 0
                    busy_seconds = 0.0
                if self._wait(config.interval_ms / 1000.0 - elapsed):
                    break
        finally:
            try:
                if capture is not None:
                    capture.__exit__(None, None, None)
            finally:
                if worker is not None:
                    worker.close()
            with self._state_lock:
                self._running = False
            self._emit(EngineEventKind.STOPPED)
