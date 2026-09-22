"""Checks on the bits of the app that differ between a source checkout, a
PyInstaller bundle, and a pip-installed wheel."""

import sys
from pathlib import Path

from openansho import __main__ as entry_point


def test_icon_path_resolves_to_the_repo_image_in_a_source_checkout():
    icon = entry_point._icon_path()

    assert icon.name == "kanji_shou_app_icon.png"
    assert icon.parent.name == "images"
    assert icon.exists()


def test_icon_path_prefers_the_copy_shipped_inside_an_installed_package(tmp_path, monkeypatch):
    """Wheels carry the icon next to the module (see pyproject's
    force-include), since an installed copy has no repo root to look in."""
    packaged_icon = tmp_path / "kanji_shou_app_icon.png"
    packaged_icon.write_bytes(b"")
    monkeypatch.setattr(entry_point, "__file__", str(tmp_path / "__main__.py"))

    assert entry_point._icon_path() == packaged_icon


def test_icon_path_uses_the_pyinstaller_extraction_directory_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert entry_point._icon_path() == tmp_path / "images" / "kanji_shou_app_icon.png"


def test_the_tutorial_text_ships_inside_the_package():
    """tutorial.txt is package data, not a repo file: `open_tutorial_project`
    reads it next to the module, so it has to travel with the wheel."""
    from openansho import tutorial

    assert (Path(tutorial.__file__).resolve().parent / "tutorial.txt").exists()
