import os

# Creating and tearing down ~140 real on-screen windows in quick succession
# crashes/segfaults the native Cocoa platform plugin on macOS. Tests don't
# need a visible window, so default to the offscreen QPA platform; this must
# run before pytest-qt's session-scoped `qapp` fixture constructs the
# QApplication. Explicitly set QT_QPA_PLATFORM beforehand to override.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
