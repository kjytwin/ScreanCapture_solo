"""ImageWatcher 설정 로드 및 검증."""

from __future__ import annotations

import configparser
import io
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG = """[watch]
reference = reference.png
monitor = 1
region = full
confidence = 0.85
disappearance_confidence = 0.80
interval_ms = 100
consecutive_matches = 2
consecutive_misses = 3
cooldown_seconds = 3

[notification]
sound = true
desktop_notification = true
save_capture = true

[storage]
log_directory = logs
capture_directory = captures
retention_days = 7
max_capture_mb = 512
max_log_mb = 5
log_backups = 3
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
    disappearance_confidence: float | None = None
    consecutive_misses: int | None = None
    max_capture_mb: int = 512
    max_log_mb: int = 5
    log_backups: int = 3


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


def validate_config(config: AppConfig, *, require_reference: bool = True) -> None:
    """메모리에서 구성한 설정도 파일 로드와 같은 규칙으로 검증한다."""
    if config.monitor < 1:
        raise ConfigError("watch.monitor 값은 1 이상이어야 합니다.")
    _require_range("watch.confidence", config.confidence, 0.0, 1.0)
    disappearance = (
        config.confidence
        if config.disappearance_confidence is None
        else config.disappearance_confidence
    )
    _require_range("watch.disappearance_confidence", disappearance, 0.0, config.confidence)
    misses = config.consecutive_matches if config.consecutive_misses is None else config.consecutive_misses
    _require_range("watch.consecutive_misses", misses, 1, 100)
    _require_range("watch.interval_ms", config.interval_ms, 10, 60_000)
    _require_range("watch.consecutive_matches", config.consecutive_matches, 1, 100)
    _require_range("watch.cooldown_seconds", config.cooldown_seconds, 0, 86_400)
    _require_range("storage.retention_days", config.retention_days, 0, 3_650)
    _require_range("storage.max_capture_mb", config.max_capture_mb, 0, 1_000_000)
    _require_range("storage.max_log_mb", config.max_log_mb, 1, 1024)
    _require_range("storage.log_backups", config.log_backups, 1, 100)
    if config.region is not None:
        if config.region.left < 0 or config.region.top < 0:
            raise ConfigError("watch.region의 left와 top은 0 이상이어야 합니다.")
        if config.region.width <= 0 or config.region.height <= 0:
            raise ConfigError("watch.region의 width와 height는 1 이상이어야 합니다.")
    if require_reference and not config.reference.is_file():
        raise ConfigError(
            f"기준 이미지를 찾을 수 없습니다: {config.reference}\n"
            "찾으려는 이미지를 reference.png로 저장하거나 settings.ini의 reference를 수정하세요."
        )


def _portable_path(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """검증한 설정을 UTF-8 INI로 원자적으로 저장한다."""
    validate_config(config)
    destination = (path or config.config_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    base = destination.parent
    parser = configparser.ConfigParser()
    parser["watch"] = {
        "reference": _portable_path(config.reference, base),
        "monitor": str(config.monitor),
        "region": "full" if config.region is None else str(config.region),
        "confidence": str(config.confidence),
        "disappearance_confidence": str(
            config.confidence
            if config.disappearance_confidence is None
            else config.disappearance_confidence
        ),
        "interval_ms": str(config.interval_ms),
        "consecutive_matches": str(config.consecutive_matches),
        "consecutive_misses": str(
            config.consecutive_matches
            if config.consecutive_misses is None
            else config.consecutive_misses
        ),
        "cooldown_seconds": str(config.cooldown_seconds),
    }
    parser["notification"] = {
        "sound": str(config.sound).lower(),
        "desktop_notification": str(config.desktop_notification).lower(),
        "save_capture": str(config.save_capture).lower(),
    }
    parser["storage"] = {
        "log_directory": _portable_path(config.log_directory, base),
        "capture_directory": _portable_path(config.capture_directory, base),
        "retention_days": str(config.retention_days),
        "max_capture_mb": str(config.max_capture_mb),
        "max_log_mb": str(config.max_log_mb),
        "log_backups": str(config.log_backups),
    }
    output = io.StringIO()
    parser.write(output)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(output.getvalue(), encoding="utf-8")
        temporary.replace(destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConfigError(f"설정 파일을 저장할 수 없습니다: {destination} ({exc})") from exc
    return destination


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
        disappearance_confidence = parser.getfloat("watch", "disappearance_confidence", fallback=confidence)
        interval_ms = parser.getint("watch", "interval_ms")
        consecutive_matches = parser.getint("watch", "consecutive_matches")
        consecutive_misses = parser.getint("watch", "consecutive_misses", fallback=consecutive_matches)
        cooldown_seconds = parser.getfloat("watch", "cooldown_seconds")
        sound = parser.getboolean("notification", "sound")
        desktop_notification = parser.getboolean("notification", "desktop_notification")
        save_capture = parser.getboolean("notification", "save_capture")
        log_directory = (base / parser.get("storage", "log_directory")).resolve()
        capture_directory = (base / parser.get("storage", "capture_directory")).resolve()
        retention_days = parser.getint("storage", "retention_days")
        max_capture_mb = parser.getint("storage", "max_capture_mb", fallback=512)
        max_log_mb = parser.getint("storage", "max_log_mb", fallback=5)
        log_backups = parser.getint("storage", "log_backups", fallback=3)
    except (configparser.Error, KeyError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"설정 값을 읽을 수 없습니다: {exc}") from exc

    config = AppConfig(
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
        disappearance_confidence=disappearance_confidence,
        consecutive_misses=consecutive_misses,
        max_capture_mb=max_capture_mb,
        max_log_mb=max_log_mb,
        log_backups=log_backups,
    )
    validate_config(config, require_reference=require_reference)
    return config

