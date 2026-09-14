"""ImageWatcher Tkinter 그래픽 사용자 인터페이스."""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import ConfigError, ensure_config, load_config
from detector import DetectorError
from capture import CaptureError
from gui_controller import GuiController, config_from_form
from diagnostics import prepare_directories, validate_environment
from version import VERSION
from watch_engine import EngineEventKind


class ImageWatcherGUI:
    POLL_MS = 250
    MAX_EVENT_ROWS = 200

    def __init__(self, root: tk.Tk, config_path: Path) -> None:
        self.root = root
        self.config_path = config_path.resolve()
        ensure_config(self.config_path)
        self.base_config = load_config(self.config_path, require_reference=False)
        self.controller = GuiController(self.base_config)
        self.variables: dict[str, tk.Variable] = {}
        self._editable: list[tk.Widget] = []
        self._monitor_numbers: dict[str, int] = {}
        self._task_results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._closing = False
        self._dirty = False

        self.root.title(f"ImageWatcher {VERSION}")
        self.root.geometry("880x720")
        self.root.minsize(780, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_style()
        self._build()
        self._load_form()
        self.refresh_monitors(show_error=False)
        for variable in self.variables.values():
            variable.trace_add("write", self._mark_dirty)
        self._dirty = False
        self.root.after(self.POLL_MS, self._poll)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("맑은 고딕", 18, "bold"))
        style.configure("Status.TLabel", font=("맑은 고딕", 11, "bold"))
        style.configure("Found.Status.TLabel", foreground="#15803d")
        style.configure("Error.Status.TLabel", foreground="#b91c1c")

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="ImageWatcher", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="화면 이미지 감시", foreground="#555555").pack(
            side="left", padx=12, pady=(8, 0)
        )

        settings = ttk.LabelFrame(outer, text="감시 설정", padding=12)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        self._entry_row(settings, 0, "기준 이미지", "reference", 0, width=48, span=3)
        browse = ttk.Button(settings, text="찾아보기", command=self.browse_reference)
        browse.grid(row=0, column=4, padx=(8, 0), sticky="ew")
        self._editable.append(browse)

        ttk.Label(settings, text="모니터").grid(row=1, column=0, sticky="w", pady=5)
        self.variables["monitor"] = tk.StringVar()
        self.monitor_box = ttk.Combobox(
            settings, textvariable=self.variables["monitor"], state="readonly", width=24
        )
        self.monitor_box.grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=5)
        self._editable.append(self.monitor_box)
        refresh = ttk.Button(settings, text="새로고침", command=self.refresh_monitors)
        refresh.grid(row=1, column=2, sticky="ew", padx=(0, 16), pady=5)
        self._editable.append(refresh)
        self._entry_row(settings, 1, "감시 영역", "region", 3, width=24)

        self._entry_row(settings, 2, "발견 기준", "confidence", 0)
        self._entry_row(settings, 2, "사라짐 기준", "disappearance_confidence", 2)
        self._entry_row(settings, 3, "검사 간격(ms)", "interval_ms", 0)
        self._entry_row(settings, 3, "발견 연속 횟수", "consecutive_matches", 2)
        self._entry_row(settings, 4, "사라짐 연속 횟수", "consecutive_misses", 0)
        self._entry_row(settings, 4, "알림 제한(초)", "cooldown_seconds", 2)
        self._entry_row(settings, 5, "캡처 보존(일)", "retention_days", 0)
        self._entry_row(settings, 5, "캡처 제한(MiB)", "max_capture_mb", 2)

        options = ttk.Frame(settings)
        options.grid(row=6, column=0, columnspan=5, sticky="w", pady=(8, 0))
        for key, label in (
            ("sound", "알림 소리"),
            ("desktop_notification", "Windows 알림"),
            ("save_capture", "감지 화면 저장"),
        ):
            variable = tk.BooleanVar()
            self.variables[key] = variable
            widget = ttk.Checkbutton(options, text=label, variable=variable)
            widget.pack(side="left", padx=(0, 20))
            self._editable.append(widget)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=12)
        self.save_button = ttk.Button(actions, text="설정 저장", command=self.save)
        self.check_button = ttk.Button(actions, text="설정 검사", command=self.check)
        self.test_button = ttk.Button(actions, text="한 번 테스트", command=self.test)
        self.start_button = ttk.Button(actions, text="감시 시작", command=self.start)
        self.pause_button = ttk.Button(actions, text="일시정지", command=self.pause_or_resume)
        self.stop_button = ttk.Button(actions, text="감시 종료", command=self.stop)
        for widget in (
            self.save_button,
            self.check_button,
            self.test_button,
            self.start_button,
            self.pause_button,
            self.stop_button,
        ):
            widget.pack(side="left", padx=(0, 8))
        self._update_controls()

        status = ttk.LabelFrame(outer, text="현재 상태", padding=12)
        status.pack(fill="x", pady=(0, 12))
        self.status_text = tk.StringVar(value="대기 중")
        self.score_text = tk.StringVar(value="유사도 점수: -")
        self.position_text = tk.StringVar(value="위치: -")
        self.performance_text = tk.StringVar(value="성능: 측정 전")
        self.status_label = ttk.Label(status, textvariable=self.status_text, style="Status.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.score_text).grid(row=0, column=1, padx=24)
        ttk.Label(status, textvariable=self.position_text).grid(row=0, column=2, padx=8)
        ttk.Label(status, textvariable=self.performance_text).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        history = ttk.LabelFrame(outer, text="최근 이벤트", padding=8)
        history.pack(fill="both", expand=True)
        self.events = ttk.Treeview(
            history,
            columns=("time", "event", "detail"),
            show="headings",
            height=10,
        )
        self.events.heading("time", text="시간")
        self.events.heading("event", text="이벤트")
        self.events.heading("detail", text="내용")
        self.events.column("time", width=90, stretch=False)
        self.events.column("event", width=110, stretch=False)
        self.events.column("detail", width=560)
        scrollbar = ttk.Scrollbar(history, orient="vertical", command=self.events.yview)
        self.events.configure(yscrollcommand=scrollbar.set)
        self.events.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _entry_row(self, parent, row, label, key, column, width=16, span=1) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=5)
        variable = tk.StringVar()
        self.variables[key] = variable
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(
            row=row,
            column=column + 1,
            columnspan=span,
            sticky="ew",
            padx=(8, 16),
            pady=5,
        )
        self._editable.append(entry)

    def _load_form(self) -> None:
        config = self.base_config
        values = {
            "reference": str(config.reference),
            "monitor": str(config.monitor),
            "region": "full" if config.region is None else str(config.region),
            "confidence": str(config.confidence),
            "disappearance_confidence": str(config.disappearance_confidence),
            "interval_ms": str(config.interval_ms),
            "consecutive_matches": str(config.consecutive_matches),
            "consecutive_misses": str(config.consecutive_misses),
            "cooldown_seconds": str(config.cooldown_seconds),
            "sound": config.sound,
            "desktop_notification": config.desktop_notification,
            "save_capture": config.save_capture,
            "retention_days": str(config.retention_days),
            "max_capture_mb": str(config.max_capture_mb),
        }
        for key, value in values.items():
            self.variables[key].set(value)
        self._dirty = False

    def _mark_dirty(self, *args) -> None:
        self._dirty = True

    def _form_values(self) -> dict[str, object]:
        values = {key: variable.get() for key, variable in self.variables.items()}
        display = str(values["monitor"])
        values["monitor"] = self._monitor_numbers.get(display, display.split(":", 1)[0])
        return values

    def _read_config(self):
        return config_from_form(self.base_config, self._form_values())

    def browse_reference(self) -> None:
        filename = filedialog.askopenfilename(
            title="기준 이미지 선택",
            filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.bmp"), ("모든 파일", "*.*")],
        )
        if filename:
            self.variables["reference"].set(filename)

    def refresh_monitors(self, show_error=True) -> None:
        try:
            monitors = self.controller.list_monitors()
            values = [f"{item.number}: {item.width}x{item.height} ({item.left},{item.top})" for item in monitors]
            self._monitor_numbers = {value: item.number for value, item in zip(values, monitors)}
            self.monitor_box.configure(values=values)
            current = int(str(self.variables["monitor"].get()).split(":", 1)[0])
            selected = next((value for value, number in self._monitor_numbers.items() if number == current), "")
            if selected:
                self.variables["monitor"].set(selected)
        except Exception as exc:
            if show_error:
                messagebox.showerror("모니터 확인 실패", str(exc), parent=self.root)

    def save(self) -> bool:
        try:
            config = self._read_config()
            self.controller.save(config)
            self.base_config = config
            self._dirty = False
            self._add_event("설정", "settings.ini 저장 완료")
            return True
        except (ConfigError, OSError) as exc:
            messagebox.showerror("설정 저장 실패", str(exc), parent=self.root)
            return False

    def check(self) -> None:
        try:
            config = self._read_config()
            prepare_directories(config)
            validate_environment(config)
            messagebox.showinfo("설정 검사", "이미지, 모니터, 감시 영역과 저장 폴더가 정상입니다.", parent=self.root)
            self._add_event("검사", "설정 검사 성공")
        except (ConfigError, CaptureError, DetectorError, OSError) as exc:
            messagebox.showerror("설정 검사 실패", str(exc), parent=self.root)

    def test(self) -> None:
        if self.controller.active:
            messagebox.showwarning("감시 실행 중", "감시를 종료한 뒤 한 번 테스트를 실행하세요.", parent=self.root)
            return
        try:
            config = self._read_config()
            prepare_directories(config)
        except (ConfigError, OSError) as exc:
            messagebox.showerror("테스트 실패", str(exc), parent=self.root)
            return
        preview = config.capture_directory / "test_preview.png"
        self.test_button.configure(state="disabled")
        self.status_text.set("한 번 테스트 중…")

        def run_test() -> None:
            try:
                result = self.controller.test_once(config, preview)
                self._task_results.put(("test_ok", (result, preview)))
            except Exception as exc:
                self._task_results.put(("test_error", exc))

        threading.Thread(target=run_test, name="imagewatcher-test", daemon=True).start()

    def start(self) -> None:
        try:
            config = self._read_config()
            prepare_directories(config)
            validate_environment(config)
            self.controller.start(config)
            self.base_config = config
            self._set_editable(False)
            self._update_controls()
        except (ConfigError, CaptureError, DetectorError, RuntimeError, OSError) as exc:
            messagebox.showerror("감시 시작 실패", str(exc), parent=self.root)

    def pause_or_resume(self) -> None:
        self.controller.pause_or_resume()
        self._update_controls()

    def stop(self) -> None:
        if self.controller.active:
            self.status_text.set("종료 중…")
            self.controller.stop(timeout=0)
            self._update_controls()

    def close(self) -> None:
        if self.controller.active:
            self._closing = True
            self.stop()
            return
        if self._dirty:
            answer = messagebox.askyesnocancel(
                "설정 저장",
                "변경한 설정을 저장하고 종료할까요?",
                parent=self.root,
            )
            if answer is None:
                return
            if answer and not self.save():
                return
        self.root.destroy()

    def _set_editable(self, enabled: bool) -> None:
        for widget in self._editable:
            if widget is self.monitor_box:
                widget.configure(state="readonly" if enabled else "disabled")
            else:
                widget.configure(state="normal" if enabled else "disabled")

    def _update_controls(self) -> None:
        active = self.controller.active
        self.start_button.configure(state="disabled" if active else "normal")
        self.save_button.configure(state="disabled" if active else "normal")
        self.check_button.configure(state="disabled" if active else "normal")
        self.test_button.configure(state="disabled" if active else "normal")
        self.pause_button.configure(state="normal" if active else "disabled")
        self.stop_button.configure(state="normal" if active else "disabled")
        self.pause_button.configure(text="재개" if self.controller.paused else "일시정지")

    def _add_event(self, event: str, detail: str, occurred_at=None) -> None:
        timestamp = occurred_at.strftime("%H:%M:%S") if occurred_at else "-"
        self.events.insert("", 0, values=(timestamp, event, detail))
        children = self.events.get_children()
        for item in children[self.MAX_EVENT_ROWS:]:
            self.events.delete(item)

    def _handle_engine_event(self, event) -> None:
        result = event.result
        if event.kind is EngineEventKind.SCAN and result is not None:
            self.score_text.set(f"유사도 점수: {result.confidence:.2%}")
            self.position_text.set(f"위치: {result.left},{result.top} ({result.width}x{result.height})")
        elif event.kind is EngineEventKind.STARTED:
            self.status_text.set("감시 중")
            self.status_label.configure(style="Status.TLabel")
            self._add_event("시작", "실시간 감시 시작", event.occurred_at)
        elif event.kind is EngineEventKind.PAUSED:
            self.status_text.set("일시정지")
            self._add_event("일시정지", "감시 일시정지", event.occurred_at)
        elif event.kind is EngineEventKind.RESUMED:
            self.status_text.set("감시 중")
            self._add_event("재개", "감시 재개", event.occurred_at)
        elif event.kind is EngineEventKind.FOUND and result is not None:
            self.status_text.set("이미지 발견")
            self.status_label.configure(style="Found.Status.TLabel")
            self._add_event("발견", f"{result.confidence:.2%} / {result.left},{result.top}", event.occurred_at)
        elif event.kind is EngineEventKind.DISAPPEARED:
            self.status_text.set("감시 중 · 미발견")
            self.status_label.configure(style="Status.TLabel")
            self._add_event("사라짐", "기준 이미지가 사라짐", event.occurred_at)
        elif event.kind is EngineEventKind.CAPTURE_SAVED:
            self._add_event("저장", str(event.capture_path), event.occurred_at)
        elif event.kind is EngineEventKind.WARNING:
            self._add_event("경고", event.message, event.occurred_at)
        elif event.kind is EngineEventKind.ERROR:
            self.status_text.set("오류")
            self.status_label.configure(style="Error.Status.TLabel")
            self._add_event("오류", event.message, event.occurred_at)
            messagebox.showerror("감시 오류", event.message, parent=self.root)
        elif event.kind is EngineEventKind.PERFORMANCE:
            self.performance_text.set(
                f"성능: {event.scans_per_second:.1f}회/초 · 평균 처리 {event.average_processing_ms:.1f}ms"
            )
        elif event.kind is EngineEventKind.STOPPED:
            if self.status_text.get() != "오류":
                self.status_text.set("대기 중")
            self._add_event("종료", "감시 종료", event.occurred_at)

    def _poll(self) -> None:
        for event in self.controller.drain_events():
            self._handle_engine_event(event)
        while True:
            try:
                kind, value = self._task_results.get_nowait()
            except queue.Empty:
                break
            self.test_button.configure(state="normal")
            if kind == "test_ok":
                result, preview = value
                state = "발견" if result.matched else "미발견"
                self.status_text.set(f"테스트: {state}")
                self.score_text.set(f"유사도 점수: {result.confidence:.2%}")
                self.position_text.set(f"위치: {result.left},{result.top} ({result.width}x{result.height})")
                self._add_event("테스트", f"{state} · 결과 이미지: {preview}")
                messagebox.showinfo(
                    "테스트 결과",
                    f"{state}\n유사도 점수: {result.confidence:.2%}\n결과 이미지: {preview}",
                    parent=self.root,
                )
            else:
                self.status_text.set("대기 중")
                messagebox.showerror("테스트 실패", str(value), parent=self.root)

        if not self.controller.active:
            self._set_editable(True)
        self._update_controls()
        if self._closing and not self.controller.active:
            self._closing = False
            self.close()
            return
        self.root.after(self.POLL_MS, self._poll)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ImageWatcher 그래픽 사용자 인터페이스")
    parser.add_argument("--config", default="settings.ini", help="설정 파일 경로")
    parser.add_argument("--version", action="version", version=f"ImageWatcherGUI {VERSION}")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: tk.Tk | None = None
    try:
        root = tk.Tk()
        if args.smoke_test:
            root.withdraw()
            ttk.Frame(root).pack()
            root.update_idletasks()
            root.destroy()
            return 0
        ImageWatcherGUI(root, Path(args.config))
        root.mainloop()
        return 0
    except (ConfigError, tk.TclError, OSError) as exc:
        message = f"[GUI 실행 오류] {exc}"
        if root is not None:
            try:
                messagebox.showerror("ImageWatcherGUI 실행 오류", message, parent=root)
            except tk.TclError:
                pass
            finally:
                try:
                    root.destroy()
                except tk.TclError:
                    pass
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
