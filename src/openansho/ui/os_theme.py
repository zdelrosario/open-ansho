from __future__ import annotations

import platform
import subprocess

SUBPROCESS_TIMEOUT_SECONDS = 2


def detect_dark_mode() -> bool:
    """Best-effort detection of the OS's current dark/light mode preference.

    Falls back to light mode (False) if the platform isn't recognized, or if
    detection fails for any reason (missing tool, unexpected output, ...).
    """
    try:
        system = platform.system()
        if system == "Darwin":
            return _detect_macos_dark_mode()
        if system == "Windows":
            return _detect_windows_dark_mode()
        if system == "Linux":
            return _detect_linux_dark_mode()
        return False
    except Exception:
        return False


def _detect_macos_dark_mode() -> bool:
    # Only set at all when the user has enabled dark mode; reads back
    # nothing (a non-zero exit) under light mode.
    result = subprocess.run(
        ["defaults", "read", "-g", "AppleInterfaceStyle"],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.returncode == 0 and result.stdout.strip() == "Dark"


def _detect_windows_dark_mode() -> bool:
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
    )
    with key:
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return value == 0


def _detect_linux_dark_mode() -> bool:
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.returncode == 0 and "dark" in result.stdout.lower()
