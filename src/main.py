"""ImageWatcher 1단계 명령행 진입점."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from config import AppConfig, ConfigError, ensure_config, load_config


VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ImageWatcher", description="화면 이미지 감시 프로그램")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--config", default="settings.ini", help="설정 파일 경로")
    parser.add_argument("--check-config", action="store_true", help="설정을 검증하고 종료")
    return parser


def print_summary(config: AppConfig) -> None:
    region = "전체 화면" if config.region is None else str(config.region)
    print("ImageWatcher Prototype")
    print(f"기준 이미지 : {config.reference}")
    print(f"감시 대상   : 모니터 {config.monitor} / {region}")
    print(f"민감도      : {config.confidence:.0%}")
    print(f"검사 간격   : {config.interval_ms}ms")


def run_stage_one(config: AppConfig) -> int:
    print_summary(config)
    print("\n1단계 실행 골격이 정상적으로 시작되었습니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n종료 요청을 받아 안전하게 종료했습니다.")
        return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    try:
        if ensure_config(config_path):
            print(f"기본 설정 파일을 생성했습니다: {config_path.resolve()}")
            print("reference.png를 준비한 뒤 다시 실행하세요.")
            return 2
        config = load_config(config_path)
        for directory in (config.log_directory, config.capture_directory):
            directory.mkdir(parents=True, exist_ok=True)
    except (ConfigError, OSError) as exc:
        print(f"[설정 오류] {exc}", file=sys.stderr)
        return 2
    if args.check_config:
        print_summary(config)
        print("\n설정 검증에 성공했습니다.")
        return 0
    return run_stage_one(config)


if __name__ == "__main__":
    raise SystemExit(main())

