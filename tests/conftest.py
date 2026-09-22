import os

# Creating and tearing down ~140 real on-screen windows in quick succession
# crashes/segfaults the native Cocoa platform plugin on macOS. Tests don't
# need a visible window, so default to the offscreen QPA platform; this must
# run before pytest-qt's session-scoped `qapp` fixture constructs the
# QApplication. Explicitly set QT_QPA_PLATFORM beforehand to override.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from openansho import user


@pytest.fixture(autouse=True)
def _isolate_username_file(tmp_path, monkeypatch):
    """The real .openansho_user sidecar lives next to the installed app, one
    per machine — redirect it into each test's own tmp_path so tests never
    read or clobber the developer's actual username file on disk. The
    site-packages branch is pinned off as well, so a test run against an
    installed copy of the package stays inside tmp_path too."""
    monkeypatch.setattr(user, "application_directory", lambda: tmp_path)
    monkeypatch.setattr(user, "installed_in_site_packages", lambda: False)
