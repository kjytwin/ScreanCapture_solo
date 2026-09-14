"""CMD 경로와 GUI 상태 전달을 포함한 탐지 경로의 처리 시간을 비교한다."""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from detector import TemplateDetector  # noqa: E402
from gui_controller import GuiController  # noqa: E402
from watch_engine import EngineEvent, EngineEventKind  # noqa: E402


def measure(detector, frame, iterations: int, callback=None) -> float:
    started = time.perf_counter()
    for _ in range(iterations):
        result = detector.detect(frame)
        if callback is not None:
            callback(
                EngineEvent(
                    EngineEventKind.SCAN,
                    datetime.now().astimezone(),
                    result=result,
                )
            )
    return (time.perf_counter() - started) / iterations * 1000


def main() -> None:
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8)
    reference = frame[250:290, 500:560, 0]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "reference.png"
        path.write_bytes(cv2.imencode(".png", reference)[1].tobytes())
        detector = TemplateDetector(path, .85)
        controller = GuiController(None)  # 이 벤치마크는 상태 전달 경로만 사용한다.
        measure(detector, frame, 5)
        cli = []
        gui = []
        for round_number in range(6):
            if round_number % 2:
                gui.append(measure(detector, frame, 20, controller._receive))
                cli.append(measure(detector, frame, 20))
            else:
                cli.append(measure(detector, frame, 20))
                gui.append(measure(detector, frame, 20, controller._receive))

        scan_event = EngineEvent(
            EngineEventKind.SCAN,
            datetime.now().astimezone(),
            result=detector.detect(frame),
        )
        delivery_started = time.perf_counter()
        for _ in range(10_000):
            controller._receive(scan_event)
        delivery_us = (time.perf_counter() - delivery_started) / 10_000 * 1_000_000
    cli_ms = statistics.median(cli)
    gui_ms = statistics.median(gui)
    delta = (gui_ms / cli_ms - 1) * 100
    print(f"CMD 경로 중앙값: {cli_ms:.3f}ms")
    print(f"GUI 전달 포함 중앙값: {gui_ms:.3f}ms")
    print(f"차이: {delta:+.2f}%")
    print(f"GUI 스캔 이벤트 전달: {delivery_us:.3f}µs/회")
    print("실제 GUI는 스캔 상태를 최대 초당 4회만 전달하므로 이 측정보다 부담이 작습니다.")


if __name__ == "__main__":
    main()
