"""Per-machine username storage, kept alongside the application (not a
project's database file).

A project's .sqlite file is meant to be shared between contributors (e.g.
via a shared drive or version control), so it must never carry anyone's
identity itself. The username instead lives in a sidecar file next to the
running application, one per machine/install, so it stays put regardless
of which project is open.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

USERNAME_FILENAME = ".openansho_user"
CONFIG_DIRNAME = "OpenAnsho"


def application_directory() -> Path:
    """Directory the running app lives in: the frozen executable's folder
    when packaged (e.g. via PyInstaller), or this package's folder when
    running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _is_library_path(path: Path) -> bool:
    """True when `path` sits inside the running interpreter's library
    directory (site-packages)."""
    paths = sysconfig.get_paths()
    library_dirs = {paths.get("purelib"), paths.get("platlib")}
    return any(
        library_dir is not None and path.is_relative_to(Path(library_dir).resolve())
        for library_dir in library_dirs
    )


def installed_in_site_packages() -> bool:
    """True when this package was installed into a Python environment's
    library directory (`pip install openansho`), as opposed to being run from
    a source checkout or an editable install, which leave the package in the
    developer's own tree."""
    return _is_library_path(Path(__file__).resolve().parent)


def config_directory() -> Path:
    """Per-user directory for app state, following each platform's convention
    (including its capitalization: XDG directories are conventionally
    lowercase, the Windows and macOS ones carry the app's display name)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / CONFIG_DIRNAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / CONFIG_DIRNAME
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / CONFIG_DIRNAME.lower()


def username_file() -> Path:
    # A pip-installed copy must not write into site-packages: that directory is
    # read-only on system-wide installs, and `pip install -U openansho` replaces
    # it, which would silently lose the username. Installed copies therefore keep
    # it in the per-user config directory instead. Frozen builds and source
    # checkouts own their directory, so they keep the sidecar file next to the
    # app, one per machine/install.
    if installed_in_site_packages():
        return config_directory() / USERNAME_FILENAME
    return application_directory() / USERNAME_FILENAME


def read_username() -> str | None:
    path = username_file()
    if not path.exists():
        return None
    name = path.read_text(encoding="utf-8").strip()
    return name or None


def write_username(username: str) -> None:
    path = username_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(username, encoding="utf-8")
