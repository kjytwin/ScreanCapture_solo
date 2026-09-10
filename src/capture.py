"""mss를 이용한 화면 캡처."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import Region


class CaptureError(RuntimeError):
    """화면 또는 모니터를 캡처할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class MonitorInfo:
    number: int
    left: int
    top: int
    width: int
    height: int


class ScreenCapture:
    def __init__(self) -> None:
        try:
            import mss
            import numpy
        except ImportError as exc:
            raise CaptureError(
                "화면 캡처 패키지가 없습니다. pip install -r requirements.txt를 실행하세요."
            ) from exc
        self._mss_module = mss
        self._numpy = numpy
        try:
            self._session = mss.mss()
        except Exception as exc:
            raise CaptureError(f"화면 캡처를 초기화할 수 없습니다: {exc}") from exc

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def monitors(self) -> list[MonitorInfo]:
        return [
            MonitorInfo(
                number=index,
                left=int(monitor["left"]),
                top=int(monitor["top"]),
                width=int(monitor["width"]),
                height=int(monitor["height"]),
            )
            for index, monitor in enumerate(self._session.monitors[1:], start=1)
        ]

    def _capture_area(self, monitor_number: int, region: Region | None) -> dict[str, int]:
        monitors = self._session.monitors
        if monitor_number < 1 or monitor_number >= len(monitors):
            available = max(0, len(monitors) - 1)
            raise CaptureError(
                f"모니터 {monitor_number}을 찾을 수 없습니다. 사용 가능한 모니터 수: {available}"
            )
        monitor = monitors[monitor_number]
        if region is None:
            return {
                "left": int(monitor["left"]),
                "top": int(monitor["top"]),
                "width": int(monitor["width"]),
                "height": int(monitor["height"]),
            }

        if (
            region.left < 0
            or region.top < 0
            or region.left + region.width > int(monitor["width"])
            or region.top + region.height > int(monitor["height"])
        ):
            raise CaptureError(
                "감시 영역이 선택한 모니터의 범위를 벗어났습니다. "
                "region 좌표는 선택한 모니터의 왼쪽 위를 0,0으로 사용합니다."
            )
        return {
            "left": int(monitor["left"]) + region.left,
            "top": int(monitor["top"]) + region.top,
            "width": region.width,
            "height": region.height,
        }

    def grab(self, monitor_number: int, region: Region | None = None):
        """BGR 순서의 NumPy 배열과 화면 절대 좌표를 반환한다."""
        area = self._capture_area(monitor_number, region)
        try:
            bgra = self._numpy.asarray(self._session.grab(area))
        except Exception as exc:
            raise CaptureError(f"화면 캡처에 실패했습니다: {exc}") from exc
        return bgra[:, :, :3].copy(), (area["left"], area["top"])

