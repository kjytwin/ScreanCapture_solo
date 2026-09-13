"""저장과 알림을 크기가 제한된 큐에서 순서대로 처리한다."""

from queue import Empty, Full, Queue
from threading import Event, Thread


class ActionWorker:
    def __init__(self, warn, capacity: int = 4) -> None:
        self._queue = Queue(maxsize=capacity)
        self._closing = Event()
        self._warn = warn
        self._thread = Thread(target=self._run, name="imagewatcher-actions", daemon=True)
        self._thread.start()

    def submit(self, action, *args) -> bool:
        if self._closing.is_set():
            return False
        try:
            self._queue.put_nowait((action, args))
            return True
        except Full:
            self._warn(("저장·알림 큐가 가득 차 이벤트 작업을 건너뛰었습니다.",))
            return False

    def _run(self) -> None:
        while not self._closing.is_set() or not self._queue.empty():
            try:
                action, args = self._queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                action(*args)
            except Exception as exc:
                self._warn((f"백그라운드 작업 실패: {exc}",))
            finally:
                self._queue.task_done()

    def close(self, timeout: float = 5.0) -> None:
        self._closing.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._warn(("종료 대기 시간을 초과했습니다. 미완료 저장·알림이 있을 수 있습니다.",))
