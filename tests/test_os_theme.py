import subprocess
import sys

from openansho.ui import os_theme


def _completed(returncode, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def test_unknown_platform_falls_back_to_light(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Java")
    assert os_theme.detect_dark_mode() is False


def test_macos_dark_mode_detected(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        os_theme.subprocess, "run", lambda *a, **k: _completed(0, "Dark\n")
    )
    assert os_theme.detect_dark_mode() is True


def test_macos_light_mode_when_key_unset(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(os_theme.subprocess, "run", lambda *a, **k: _completed(1, ""))
    assert os_theme.detect_dark_mode() is False


def test_macos_falls_back_to_light_on_error(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Darwin")

    def raise_missing_tool(*args, **kwargs):
        raise FileNotFoundError("defaults not found")

    monkeypatch.setattr(os_theme.subprocess, "run", raise_missing_tool)
    assert os_theme.detect_dark_mode() is False


def test_linux_dark_mode_detected(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        os_theme.subprocess,
        "run",
        lambda *a, **k: _completed(0, "'prefers-dark'\n"),
    )
    assert os_theme.detect_dark_mode() is True


def test_linux_light_mode_detected(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        os_theme.subprocess, "run", lambda *a, **k: _completed(0, "'default'\n")
    )
    assert os_theme.detect_dark_mode() is False


def test_linux_falls_back_to_light_when_gsettings_missing(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Linux")

    def raise_missing_tool(*args, **kwargs):
        raise FileNotFoundError("gsettings not found")

    monkeypatch.setattr(os_theme.subprocess, "run", raise_missing_tool)
    assert os_theme.detect_dark_mode() is False


def test_windows_dark_mode_detected(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Windows")

    class FakeWinreg:
        HKEY_CURRENT_USER = object()

        @staticmethod
        def OpenKey(hive, path):
            return _FakeKey()

        @staticmethod
        def QueryValueEx(key, name):
            return (0, 4)  # AppsUseLightTheme == 0 means dark mode

    class _FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg)
    assert os_theme.detect_dark_mode() is True


def test_windows_light_mode_detected(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Windows")

    class FakeWinreg:
        HKEY_CURRENT_USER = object()

        @staticmethod
        def OpenKey(hive, path):
            return _FakeKey()

        @staticmethod
        def QueryValueEx(key, name):
            return (1, 4)  # AppsUseLightTheme == 1 means light mode

    class _FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg)
    assert os_theme.detect_dark_mode() is False


def test_windows_falls_back_to_light_on_missing_registry_key(monkeypatch):
    monkeypatch.setattr(os_theme.platform, "system", lambda: "Windows")

    class FakeWinreg:
        HKEY_CURRENT_USER = object()

        @staticmethod
        def OpenKey(hive, path):
            raise FileNotFoundError("registry key not found")

    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg)
    assert os_theme.detect_dark_mode() is False
