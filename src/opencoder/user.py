"""Per-machine username storage, kept alongside (not inside) a project file.

A project's .sqlite file is meant to be shared between contributors (e.g.
via a shared drive or version control), so each contributor's name is
stored in a sidecar file next to it instead of in the database — that way
different users opening the same project file are each associated with
their own identity.
"""

from __future__ import annotations

from pathlib import Path

USERNAME_FILENAME = ".opencoder_user"


def username_file(project_path: Path) -> Path:
    return project_path.parent / USERNAME_FILENAME


def read_username(project_path: Path) -> str | None:
    path = username_file(project_path)
    if not path.exists():
        return None
    name = path.read_text(encoding="utf-8").strip()
    return name or None


def write_username(project_path: Path, username: str) -> None:
    username_file(project_path).write_text(username, encoding="utf-8")
