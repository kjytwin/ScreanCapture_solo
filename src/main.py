"""ImageWatcher 명령행 진입점."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from capture import CaptureError, ScreenCapture
from config import AppConfig, ConfigError, ensure_config, load_config
from detector import DetectorError, TemplateDetector
from diagnostics import prepare_directories, validate_environment
from version import VERSION
from watch_engine import EngineEvent, EngineEventKind, WatchEngine


def configure_console() -> None:
    """Windows 콘솔과 Python 출력 인코딩을 UTF-8로 일치시킨다."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except (AttributeError, OSError):
        pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


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
    parser.add_argument("--test-output", type=Path, help="--test 감지 위치를 표시할 PNG 저장 경로")
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
    print(f"발견 기준   : {config.confidence:.0%}")
    print(f"검사 간격   : {config.interval_ms}ms")


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


def test_once(config: AppConfig, output: Path | None = None) -> int:
    detector = TemplateDetector(config.reference, config.confidence)
    with ScreenCapture() as capture:
        frame, origin = capture.grab(config.monitor, config.region)
    result = detector.detect(frame, origin)
    if output is not None:
        from detector import save_detection_preview

        save_detection_preview(frame, result, origin, output)
        print(f"검사 이미지 : {output.resolve()}")
    state = "발견" if result.matched else "미발견"
    print_summary(config)
    print()
    print(
        f"검사 결과   : {state}\n"
        f"최고 유사도 점수 : {result.confidence:.2%}\n"
        f"최고 위치   : {result.left},{result.top} "
        f"({result.width}x{result.height})"
    )
    return 0 if result.matched else 1


def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


def _print_warnings(warnings: tuple[str, ...]) -> None:
    for warning in warnings:
        print(f"[경고] {warning}", file=sys.stderr)


def run_watcher(config: AppConfig) -> int:
    print_summary(config)
    print("\n실시간 감시를 시작했습니다.\n종료하려면 Ctrl+C를 누르세요.")

    def report(event: EngineEvent) -> None:
        result = event.result
        if event.kind is EngineEventKind.FOUND and result is not None:
            print(
                f"[{_timestamp()}] 이미지 발견 | 유사도 점수 {result.confidence:.2%} "
                f"| 위치 {result.left},{result.top} ({result.width}x{result.height})"
            )
        elif event.kind is EngineEventKind.DISAPPEARED:
            print(f"[{_timestamp()}] 이미지 사라짐")
        elif event.kind is EngineEventKind.CAPTURE_SAVED:
            print(f"[{_timestamp()}] 캡처 저장 | {event.capture_path}")
        elif event.kind is EngineEventKind.WARNING:
            _print_warnings((event.message,))
        elif event.kind is EngineEventKind.PERFORMANCE:
            print(
                f"[{_timestamp()}] 검사 성능 | {event.scans_per_second:.1f}회/초 "
                f"| 평균 처리 {event.average_processing_ms:.1f}ms"
            )

    engine = WatchEngine(
        config,
        report,
        capture_factory=ScreenCapture,
        detector_factory=TemplateDetector,
        monotonic=time.monotonic,
        perf_counter=time.perf_counter,
        waiter=lambda seconds: (time.sleep(seconds), False)[1],
    )
    try:
        engine.run()
    except KeyboardInterrupt:
        print("\n종료 요청을 받았습니다.")
        engine.stop()
    finally:
        print("감시를 안전하게 종료했습니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_console()
    args = build_parser().parse_args(argv)
    if args.test_output is not None and not args.test:
        build_parser().error("--test-output은 --test와 함께 사용하세요.")
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
            validate_environment(config)
            print_summary(config)
            print("\n설정 검증에 성공했습니다.")
            return 0
        if args.test:
            return test_once(config, args.test_output)
        return run_watcher(config)
    except ConfigError as exc:
        print(f"[설정 오류] {exc}", file=sys.stderr)
        return 2
    except (CaptureError, DetectorError, OSError) as exc:
        print(f"[실행 오류] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
