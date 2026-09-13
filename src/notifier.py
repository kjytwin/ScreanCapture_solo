"""감지 시 Windows 소리와 데스크톱 알림을 표시한다."""

from __future__ import annotations


class Notifier:
    def __init__(self, sound: bool, desktop_notification: bool) -> None:
        self.sound = sound
        self.desktop_notification = desktop_notification

    def notify_found(self, confidence: float) -> tuple[str, ...]:
        """알림별 실패를 경고로 반환하고 다른 알림은 계속 시도한다."""
        warnings: list[str] = []
        if self.sound:
            try:
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except (ImportError, RuntimeError, OSError) as exc:
                warnings.append(f"알림 소리를 재생하지 못했습니다: {exc}")

        if self.desktop_notification:
            try:
                from winotify import Notification

                toast = Notification(
                    app_id="ImageWatcher",
                    title="ImageWatcher",
                    msg=f"기준 이미지를 발견했습니다. 유사도 점수 {confidence:.2%}",
                    duration="short",
                )
                toast.show()
            except Exception as exc:
                # Windows 알림 API와 외부 패키지가 내는 환경별 예외를 격리한다.
                warnings.append(f"Windows 알림을 표시하지 못했습니다: {exc}")
        return tuple(warnings)

