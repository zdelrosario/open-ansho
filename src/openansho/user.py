"""Per-machine username storage, kept alongside the application (not a
project's database file).

A project's .sqlite file is meant to be shared between contributors (e.g.
via a shared drive or version control), so it must never carry anyone's
identity itself. The username instead lives in a sidecar file next to the
running application, one per machine/install, so it stays put regardless
of which project is open.
"""

from __future__ import annotations

import sys
from pathlib import Path

USERNAME_FILENAME = ".openansho_user"


def application_directory() -> Path:
    """Directory the running app lives in: the frozen executable's folder
    when packaged (e.g. via PyInstaller), or this package's folder when
    running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def username_file() -> Path:
    return application_directory() / USERNAME_FILENAME


def read_username() -> str | None:
    path = username_file()
    if not path.exists():
        return None
    name = path.read_text(encoding="utf-8").strip()
    return name or None


def write_username(username: str) -> None:
    username_file().write_text(username, encoding="utf-8")
