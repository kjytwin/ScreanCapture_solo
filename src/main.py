"""ImageWatcher 명령행 진입점."""

from __future__ import annotations

import argparse
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path

from capture import CaptureError, ScreenCapture
from config import AppConfig, ConfigError, ensure_config, load_config
from detector import DetectorError, TemplateDetector
from event_logger import EventLogger
from notifier import Notifier
from watcher import DetectionState, EventKind
from worker import ActionWorker


VERSION = "0.6.0"


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


def prepare_directories(config: AppConfig) -> None:
    for label, directory in (
        ("로그", config.log_directory),
        ("캡처", config.capture_directory),
    ):
        if directory.exists() and not directory.is_dir():
            raise ConfigError(f"{label} 경로가 폴더가 아닙니다: {directory}")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b"ImageWatcher storage check")
                probe.flush()
        except OSError as exc:
            raise ConfigError(f"{label} 폴더를 준비하거나 쓸 수 없습니다: {directory} ({exc})") from exc


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


def validate_environment(config: AppConfig) -> None:
    detector = TemplateDetector(config.reference, config.confidence)
    with ScreenCapture() as capture:
        frame, origin = capture.grab(config.monitor, config.region)
    detector.detect(frame, origin)


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
    detector = TemplateDetector(config.reference, config.confidence)
    state = DetectionState(config.consecutive_matches, config.cooldown_seconds,
                           config.consecutive_misses)
    event_logger = EventLogger(config.log_directory, config.capture_directory,
                               config.save_capture, config.retention_days,
                               config.max_capture_mb, config.max_log_mb, config.log_backups)
    notifier = Notifier(config.sound, config.desktop_notification)
    worker = ActionWorker(_print_warnings)

    def cleanup():
        _print_warnings(event_logger.cleanup_old_captures())

    def found(result, frame, occurred_at, allowed):
        recorded = event_logger.record_found(result, frame, occurred_at, allowed)
        _print_warnings(recorded.warnings)
        if recorded.capture_path:
            print(f"[{_timestamp()}] 캡처 저장 | {recorded.capture_path}")
        if allowed:
            _print_warnings(notifier.notify_found(result.confidence))
        cleanup()

    def disappeared(occurred_at):
        _print_warnings(event_logger.record_disappeared(occurred_at).warnings)

    def capture_error(message):
        _print_warnings(event_logger.record_error(message))

    worker.submit(cleanup)
    print_summary(config)
    print("\n실시간 감시를 시작했습니다.\n종료하려면 Ctrl+C를 누르세요.")
    capture = None
    failures = 0
    next_cleanup = time.monotonic() + 3600
    stats_started = time.perf_counter()
    cycles = 0
    busy_seconds = 0.0
    try:
        while True:
            cycle_started = time.perf_counter()
            try:
                if capture is None:
                    capture = ScreenCapture()
                    capture.__enter__()
                frame, origin = capture.grab(config.monitor, config.region)
            except CaptureError as exc:
                failures += 1
                state.reset_pending()
                message = f"화면 캡처 실패 {failures}/3: {exc}"
                _print_warnings((message,))
                worker.submit(capture_error, message)
                if capture is not None:
                    capture.__exit__(None, None, None)
                    capture = None
                if failures >= 3:
                    raise CaptureError("화면 캡처가 연속 3회 실패했습니다. 화면 세션과 모니터 설정을 확인하세요.") from exc
                time.sleep(float(failures))
                continue
            failures = 0
            result = detector.detect(frame, origin)
            threshold = config.disappearance_confidence if state.present else config.confidence
            if threshold is None:
                threshold = config.confidence
            event = state.update(result.confidence >= threshold, time.monotonic())
            if event is not None and event.kind is EventKind.FOUND:
                print(f"[{_timestamp()}] 이미지 발견 | 유사도 점수 {result.confidence:.2%} "
                      f"| 위치 {result.left},{result.top} ({result.width}x{result.height})")
                worker.submit(found, result, frame if config.save_capture else None,
                              datetime.now().astimezone(), event.notification_allowed)
            elif event is not None and event.kind is EventKind.DISAPPEARED:
                print(f"[{_timestamp()}] 이미지 사라짐")
                worker.submit(disappeared, datetime.now().astimezone())
            now = time.monotonic()
            if now >= next_cleanup:
                if worker.submit(cleanup):
                    next_cleanup = now + 3600
            elapsed = time.perf_counter() - cycle_started
            cycles += 1
            busy_seconds += elapsed
            stats_elapsed = time.perf_counter() - stats_started
            if stats_elapsed >= 60:
                print(f"[{_timestamp()}] 검사 성능 | {cycles / stats_elapsed:.1f}회/초 "
                      f"| 평균 처리 {busy_seconds / cycles * 1000:.1f}ms")
                stats_started = time.perf_counter()
                cycles = 0
                busy_seconds = 0.0
            remaining = config.interval_ms / 1000.0 - elapsed
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("\n종료 요청을 받았습니다.")
        return 0
    finally:
        try:
            if capture is not None:
                capture.__exit__(None, None, None)
        finally:
            worker.close()
        print("감시를 안전하게 종료했습니다.")


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
