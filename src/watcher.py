"""연속 감지, 상태 전환, 중복 알림 제한을 관리한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EventKind(str, Enum):
    FOUND = "found"
    DISAPPEARED = "disappeared"


@dataclass(frozen=True)
class WatchEvent:
    kind: EventKind
    notification_allowed: bool = True


class DetectionState:
    """프레임 단위 결과를 안정적인 발견/사라짐 이벤트로 변환한다."""

    def __init__(self, consecutive_matches: int, cooldown_seconds: float,
                 consecutive_misses: int | None = None) -> None:
        if consecutive_matches < 1:
            raise ValueError("consecutive_matches는 1 이상이어야 합니다.")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds는 0 이상이어야 합니다.")
        self._required = consecutive_matches
        self._required_misses = consecutive_matches if consecutive_misses is None else consecutive_misses
        if self._required_misses < 1:
            raise ValueError("consecutive_misses는 1 이상이어야 합니다.")
        self._cooldown = cooldown_seconds
        self._matches = 0
        self._misses = 0
        self._present = False
        self._last_notification_at: float | None = None

    @property
    def present(self) -> bool:
        return self._present

    def update(self, matched: bool, now: float) -> WatchEvent | None:
        if matched:
            self._misses = 0
            if self._present:
                self._matches = 0
                return None
            self._matches += 1
            if self._matches < self._required:
                return None

            self._matches = 0
            self._present = True
            notification_allowed = (
                self._last_notification_at is None
                or now - self._last_notification_at >= self._cooldown
            )
            if notification_allowed:
                self._last_notification_at = now
            return WatchEvent(EventKind.FOUND, notification_allowed)

        self._matches = 0
        if not self._present:
            self._misses = 0
            return None
        self._misses += 1
        if self._misses < self._required_misses:
            return None

        self._misses = 0
        self._present = False
        return WatchEvent(EventKind.DISAPPEARED)

    def reset_pending(self) -> None:
        """관측 실패는 연속 프레임을 끊되 마지막 확정 상태는 유지한다."""
        self._matches = 0
        self._misses = 0

