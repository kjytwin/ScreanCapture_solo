"""Tk GUI와 감시 엔진 사이의 상태·스레드·설정 변환 계층."""

from __future__ import annotations

import queue
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from capture import ScreenCapture
from config import AppConfig, ConfigError, Region, save_config, validate_config
from detector import TemplateDetector, save_detection_preview
from watch_engine import EngineEvent, EngineEventKind, WatchEngine


def parse_region(value: str) -> Region | None:
    value = value.strip()
    if value.lower() == "full":
        return None
    try:
        parts = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ConfigError("감시 영역은 full 또는 left,top,width,height 형식이어야 합니다.") from exc
    if len(parts) != 4:
        raise ConfigError("감시 영역에는 정확히 네 개의 숫자가 필요합니다.")
    region = Region(*parts)
    if region.left < 0 or region.top < 0 or region.width < 1 or region.height < 1:
        raise ConfigError("감시 영역의 좌표는 0 이상, 크기는 1 이상이어야 합니다.")
    return region


def config_from_form(base: AppConfig, values: dict[str, object]) -> AppConfig:
    """GUI 문자열 값을 AppConfig로 변환하고 범위를 검증한다."""
    try:
        reference = Path(str(values["reference"]).strip()).expanduser().resolve()
        config = replace(
            base,
            reference=reference,
            monitor=int(values["monitor"]),
            region=parse_region(str(values["region"])),
            confidence=float(values["confidence"]),
            disappearance_confidence=float(values["disappearance_confidence"]),
            interval_ms=int(values["interval_ms"]),
            consecutive_matches=int(values["consecutive_matches"]),
            consecutive_misses=int(values["consecutive_misses"]),
            cooldown_seconds=float(values["cooldown_seconds"]),
            sound=_as_bool(values["sound"]),
            desktop_notification=_as_bool(values["desktop_notification"]),
            save_capture=_as_bool(values["save_capture"]),
            retention_days=int(values["retention_days"]),
            max_capture_mb=int(values["max_capture_mb"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"설정 값의 숫자 형식을 확인하세요: {exc}") from exc
    validate_config(config)
    return config


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ConfigError(f"참/거짓 설정 값이 올바르지 않습니다: {value}")


class GuiController:
    def __init__(self, config: AppConfig, engine_factory=WatchEngine) -> None:
        self.config = config
        self._engine_factory = engine_factory
        self._engine: WatchEngine | None = None
        self._thread: threading.Thread | None = None
        self._events: queue.Queue[EngineEvent] = queue.Queue(maxsize=200)
        self._latest_scan: EngineEvent | None = None
        self._scan_lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._engine is not None and self._engine.paused

    def _receive(self, event: EngineEvent) -> None:
        if event.kind is EngineEventKind.SCAN:
            with self._scan_lock:
                self._latest_scan = event
            return
        try:
            self._events.put_nowait(event)
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            self._events.put_nowait(event)

    def drain_events(self) -> list[EngineEvent]:
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        with self._scan_lock:
            if self._latest_scan is not None:
                events.append(self._latest_scan)
                self._latest_scan = None
        return events

    def save(self, config: AppConfig) -> None:
        if self.active:
            raise ConfigError("감시를 중지한 뒤 설정을 저장하세요.")
        save_config(config)
        self.config = config

    def list_monitors(self):
        with ScreenCapture() as capture:
            return capture.monitors()

    def test_once(self, config: AppConfig, preview_path: Path):
        detector = TemplateDetector(config.reference, config.confidence)
        with ScreenCapture() as capture:
            frame, origin = capture.grab(config.monitor, config.region)
        result = detector.detect(frame, origin)
        save_detection_preview(frame, result, origin, preview_path)
        return result

    def start(self, config: AppConfig) -> None:
        if self.active:
            raise RuntimeError("감시가 이미 실행 중입니다.")
        validate_config(config)
        self.config = config
        self._engine = self._engine_factory(
            config,
            self._receive,
            emit_scan_events=True,
            scan_event_interval=0.25,
        )

        def run() -> None:
            try:
                self._engine.run()
            except Exception as exc:
                self._receive(
                    EngineEvent(
                        EngineEventKind.ERROR,
                        occurred_at=datetime.now().astimezone(),
                        message=str(exc),
                    )
                )

        self._thread = threading.Thread(target=run, name="imagewatcher-detection", daemon=True)
        self._thread.start()

    def pause_or_resume(self) -> None:
        if self._engine is None or not self.active:
            return
        if self._engine.paused:
            self._engine.resume()
        else:
            self._engine.pause()

    def stop(self, timeout: float = 6.0) -> bool:
        if self._engine is not None:
            self._engine.stop()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self.active
