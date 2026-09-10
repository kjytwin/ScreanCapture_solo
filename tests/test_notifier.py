from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from notifier import Notifier  # noqa: E402


class NotifierTests(unittest.TestCase):
    def test_disabled_notifications_do_nothing(self) -> None:
        notifier = Notifier(sound=False, desktop_notification=False)
        self.assertEqual(notifier.notify_found(0.9), ())

    def test_toast_failure_is_returned_as_warning(self) -> None:
        fake_notification = MagicMock()
        fake_notification.return_value.show.side_effect = RuntimeError("toast failed")
        fake_module = MagicMock(Notification=fake_notification)
        with patch.dict(sys.modules, {"winotify": fake_module}):
            warnings = Notifier(False, True).notify_found(0.9)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Windows 알림", warnings[0])

    def test_sound_and_toast_success_paths_are_called(self) -> None:
        fake_sound = MagicMock()
        fake_sound.MB_ICONASTERISK = 64
        fake_notification = MagicMock()
        fake_toast = fake_notification.return_value
        fake_winotify = MagicMock(Notification=fake_notification)
        with patch.dict(
            sys.modules,
            {"winsound": fake_sound, "winotify": fake_winotify},
        ):
            warnings = Notifier(True, True).notify_found(0.9123)
        self.assertEqual(warnings, ())
        fake_sound.MessageBeep.assert_called_once_with(64)
        fake_notification.assert_called_once()
        fake_toast.show.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
