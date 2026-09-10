"""ImageWatcher 명령행 진입점."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from capture import CaptureError, ScreenCapture
from config import AppConfig, ConfigError, ensure_config, load_config
from detector import DetectorError, TemplateDetector
from watcher import DetectionState, EventKind


VERSION = "0.3.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ImageWatcher",
        description="Windows 화면의 기준 이미지를 실시간으로 관찰합니다.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--config", default="settings.ini", help="설정 파일 경로")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="기준 이미지 확인을 포함해 설정을 검증한 뒤 종료",
    )
    parser.add_argument("--test", action="store_true", help="화면을 한 번 검사하고 종료")
    parser.add_argument(
        "--list-monitors", action="store_true", help="사용 가능한 모니터 정보를 출력하고 종료"
    )
    return parser


def print_summary(config: AppConfig) -> None:
    region = "전체 화면" if config.region is None else str(config.region)
    print("ImageWatcher Prototype")
    print()
    print(f"기준 이미지 : {config.reference}")
    print(f"감시 대상   : 모니터 {config.monitor} / {region}")
    print(f"민감도      : {config.confidence:.0%}")
    print(f"검사 간격   : {config.interval_ms}ms")


def prepare_directories(config: AppConfig) -> None:
    for label, directory in (
        ("로그", config.log_directory),
        ("캡처", config.capture_directory),
    ):
        if directory.exists() and not directory.is_dir():
            raise ConfigError(f"{label} 경로가 폴더가 아닙니다: {directory}")
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"{label} 폴더를 만들 수 없습니다: {directory} ({exc})") from exc


def list_monitors() -> int:
    with ScreenCapture() as capture:
        monitors = capture.monitors()
    if not monitors:
        raise CaptureError("사용 가능한 모니터가 없습니다.")
    print("사용 가능한 모니터")
    for monitor in monitors:
        print(
            f"  {monitor.number}: {monitor.width}x{monitor.height} "
            f"(화면 좌표 {monitor.left},{monitor.top})"
        )
    return 0


def test_once(config: AppConfig) -> int:
    detector = TemplateDetector(config.reference, config.confidence)
    with ScreenCapture() as capture:
        frame, origin = capture.grab(config.monitor, config.region)
    result = detector.detect(frame, origin)
    state = "발견" if result.matched else "미발견"
    print_summary(config)
    print()
    print(
        f"검사 결과   : {state}\n"
        f"최고 일치율 : {result.confidence:.2%}\n"
        f"최고 위치   : {result.left},{result.top} "
        f"({result.width}x{result.height})"
    )
    return 0 if result.matched else 1


def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


def run_watcher(config: AppConfig) -> int:
    detector = TemplateDetector(config.reference, config.confidence)
    state = DetectionState(config.consecutive_matches, config.cooldown_seconds)
    print_summary(config)
    print()
    print("실시간 감시를 시작했습니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    try:
        with ScreenCapture() as capture:
            while True:
                cycle_started = time.perf_counter()
                frame, origin = capture.grab(config.monitor, config.region)
                result = detector.detect(frame, origin)
                event = state.update(result.matched, time.monotonic())

                if event is not None and event.kind is EventKind.FOUND:
                    print(
                        f"[{_timestamp()}] 이미지 발견 | 일치율 {result.confidence:.2%} "
                        f"| 위치 {result.left},{result.top} "
                        f"({result.width}x{result.height})"
                    )
                elif event is not None and event.kind is EventKind.DISAPPEARED:
                    print(f"[{_timestamp()}] 이미지 사라짐")

                elapsed = time.perf_counter() - cycle_started
                remaining = config.interval_ms / 1000.0 - elapsed
                if remaining > 0:
                    time.sleep(remaining)
    except KeyboardInterrupt:
        print("\n종료 요청을 받아 안전하게 종료했습니다.")
        return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)

    try:
        if args.list_monitors:
            return list_monitors()
        created = ensure_config(config_path)
        if created:
            print(f"기본 설정 파일을 생성했습니다: {config_path.resolve()}")
            print("reference.png를 준비한 뒤 다시 실행하세요.")
            return 2
        config = load_config(config_path)
        prepare_directories(config)
        if args.check_config:
            print_summary(config)
            print("\n설정 검증에 성공했습니다.")
            return 0
        if args.test:
            return test_once(config)
        return run_watcher(config)
    except ConfigError as exc:
        print(f"[설정 오류] {exc}", file=sys.stderr)
        return 2
    except (CaptureError, DetectorError, OSError) as exc:
        print(f"[실행 오류] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
