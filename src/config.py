"""ImageWatcher 설정 로드 및 검증."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG = """[watch]
reference = reference.png
monitor = 1
region = full
confidence = 0.85
interval_ms = 100
consecutive_matches = 2
cooldown_seconds = 3

[notification]
sound = true
desktop_notification = true
save_capture = true

[storage]
log_directory = logs
capture_directory = captures
retention_days = 7
"""


class ConfigError(ValueError):
    """사용자가 수정할 수 있는 설정 오류."""


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    def __str__(self) -> str:
        return f"{self.left},{self.top},{self.width},{self.height}"


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    reference: Path
    monitor: int
    region: Region | None
    confidence: float
    interval_ms: int
    consecutive_matches: int
    cooldown_seconds: float
    sound: bool
    desktop_notification: bool
    save_capture: bool
    log_directory: Path
    capture_directory: Path
    retention_days: int


def ensure_config(path: Path) -> bool:
    """설정 파일이 없으면 기본 파일을 만들고 True를 반환한다."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return True


def _parse_region(value: str) -> Region | None:
    if value.strip().lower() == "full":
        return None
    try:
        parts = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ConfigError("watch.region은 full 또는 left,top,width,height 형식이어야 합니다.") from exc
    if len(parts) != 4:
        raise ConfigError("watch.region은 정확히 네 개의 숫자를 사용해야 합니다.")
    left, top, width, height = parts
    if width <= 0 or height <= 0:
        raise ConfigError("watch.region의 width와 height는 1 이상이어야 합니다.")
    return Region(left, top, width, height)


def _require_range(name: str, value: float, minimum: float, maximum: float) -> None:
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} 값은 {minimum} 이상 {maximum} 이하여야 합니다.")


def load_config(path: Path, *, require_reference: bool = True) -> AppConfig:
    path = path.resolve()
    parser = configparser.ConfigParser()
    try:
        with path.open("r", encoding="utf-8") as config_file:
            parser.read_file(config_file)
        for section in ("watch", "notification", "storage"):
            if not parser.has_section(section):
                raise ConfigError(f"필수 설정 영역 [{section}]이 없습니다.")

        base = path.parent
        reference = (base / parser.get("watch", "reference")).resolve()
        monitor = parser.getint("watch", "monitor")
        region = _parse_region(parser.get("watch", "region"))
        confidence = parser.getfloat("watch", "confidence")
        interval_ms = parser.getint("watch", "interval_ms")
        consecutive_matches = parser.getint("watch", "consecutive_matches")
        cooldown_seconds = parser.getfloat("watch", "cooldown_seconds")
        sound = parser.getboolean("notification", "sound")
        desktop_notification = parser.getboolean("notification", "desktop_notification")
        save_capture = parser.getboolean("notification", "save_capture")
        log_directory = (base / parser.get("storage", "log_directory")).resolve()
        capture_directory = (base / parser.get("storage", "capture_directory")).resolve()
        retention_days = parser.getint("storage", "retention_days")
    except (configparser.Error, KeyError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"설정 값을 읽을 수 없습니다: {exc}") from exc

    if monitor < 1:
        raise ConfigError("watch.monitor 값은 1 이상이어야 합니다.")
    _require_range("watch.confidence", confidence, 0.0, 1.0)
    _require_range("watch.interval_ms", interval_ms, 10, 60_000)
    _require_range("watch.consecutive_matches", consecutive_matches, 1, 100)
    _require_range("watch.cooldown_seconds", cooldown_seconds, 0, 86_400)
    _require_range("storage.retention_days", retention_days, 0, 3_650)
    if require_reference and not reference.is_file():
        raise ConfigError(
            f"기준 이미지를 찾을 수 없습니다: {reference}\n"
            "찾으려는 이미지를 reference.png로 저장하거나 settings.ini의 reference를 수정하세요."
        )

    return AppConfig(
        config_path=path,
        reference=reference,
        monitor=monitor,
        region=region,
        confidence=confidence,
        interval_ms=interval_ms,
        consecutive_matches=consecutive_matches,
        cooldown_seconds=cooldown_seconds,
        sound=sound,
        desktop_notification=desktop_notification,
        save_capture=save_capture,
        log_directory=log_directory,
        capture_directory=capture_directory,
        retention_days=retention_days,
    )

