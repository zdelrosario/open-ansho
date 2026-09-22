# Makefile for building the OpenAnsho desktop app with PyInstaller.
#
# PyInstaller does not cross-compile: it can only build an executable for
# the OS it runs on. So build-mac must run on macOS, build-windows on
# Windows, and build-linux on Linux (e.g. as separate jobs in a CI matrix).
# `make build` builds for whichever platform you're currently on.

APP_NAME := OpenAnsho
ENTRY_POINT := src/openansho/__main__.py
ICON := images/kanji_shou_app_icon.png
TUTORIAL := src/openansho/tutorial.txt
DIST_DIR := dist
BUILD_DIR := build
VENV := .venv

# --add-data uses a platform-specific separator between source and destination.
ifeq ($(OS),Windows_NT)
    VENV_BIN := $(VENV)/Scripts
    SYSTEM_PYTHON := python
    ADD_DATA := $(ICON);images
    ADD_TUTORIAL := $(TUTORIAL);openansho
else
    VENV_BIN := $(VENV)/bin
    SYSTEM_PYTHON := python3
    ADD_DATA := $(ICON):images
    ADD_TUTORIAL := $(TUTORIAL):openansho
endif

PYTHON := $(VENV_BIN)/python
PIP := $(VENV_BIN)/pip
PYINSTALLER := $(VENV_BIN)/pyinstaller
PYTEST := $(VENV_BIN)/pytest

PYPI_DIR := $(DIST_DIR)/pypi

.PHONY: help venv install install-build install-publish test clean build build-mac build-windows build-linux dist publish publish-test

help:
	@echo "Targets:"
	@echo "  venv           Create the virtualenv at $(VENV)"
	@echo "  install        Install the package with dev dependencies"
	@echo "  install-build  Install PyInstaller into the virtualenv"
	@echo "  test           Run the full test suite"
	@echo "  build-mac      Build a macOS .app bundle (must run on macOS)"
	@echo "  build-windows  Build a Windows .exe (must run on Windows)"
	@echo "  build-linux    Build a Linux binary (must run on Linux)"
	@echo "  build          Build for the current platform"
	@echo "  dist           Build the PyPI sdist + wheel into $(PYPI_DIR)"
	@echo "  publish-test   Upload the sdist + wheel to TestPyPI"
	@echo "  publish        Upload the sdist + wheel to PyPI"
	@echo "  clean          Remove build/dist artifacts and .spec files"

$(VENV_BIN)/python:
	$(SYSTEM_PYTHON) -m venv $(VENV)

venv: $(VENV_BIN)/python

install: venv
	$(PIP) install -e ".[dev]"

install-build: venv
	$(PIP) install -e ".[build]"

install-publish: venv
	$(PIP) install -e ".[publish]"

# Note: the full suite is known to hang in Claude Code's sandboxed/offscreen
# environment (see CLAUDE.md) — this target is meant for a real terminal or CI.
test: install
	$(PYTEST)

clean:
	rm -rf $(BUILD_DIR) $(DIST_DIR) *.spec

# --- Platform builds --------------------------------------------------------
#
# Windows and Linux build with --onefile, which bundles the interpreter, Qt,
# and the app into a single self-contained executable. PyInstaller's default
# one-dir mode instead emits the executable next to an _internal/ folder
# holding the interpreter library (python311.dll / libpython3.11.so), which the
# launcher resolves relative to its own location — so the moment someone
# downloads or copies just the executable (e.g. grabbing the single file off
# the `builds` branch, where GitHub only offers per-file downloads), it dies
# with "Failed to load Python DLL ...\_internal\python311.dll" or the Linux
# equivalent. A single file has no such loose ends. Costs a few seconds of
# startup while it unpacks to a temp dir.
#
# macOS stays one-dir, since --windowed there wraps the result in a .app bundle
# and a bundle is a directory by definition.
#
# Both Linux and macOS ship their result as a tarball (see build-linux for the
# full reasoning). The short version: the artifact pipeline mangles anything it
# ships loose. actions/upload-artifact zips without preserving Unix modes, and
# an HTTP download carries no permission metadata at all, so the executable bit
# is gone by the time a user has the file. macOS additionally needs the archive
# because upload-artifact follows symlinks: it dereferences every
# Versions/Current -> Versions/A link inside the Qt frameworks into a second
# full copy, which both doubles the size and invalidates the _CodeSignature
# manifest that describes the symlinked layout. tar records modes and symlinks
# inside the archive, so all of it survives however the archive travelled.

build-mac: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --windowed --noconfirm --clean \
		--icon $(ICON) --add-data "$(ADD_DATA)" --add-data "$(ADD_TUTORIAL)" \
		--distpath $(DIST_DIR)/mac --workpath $(BUILD_DIR)/mac \
		$(ENTRY_POINT)
	chmod +x "$(DIST_DIR)/mac/$(APP_NAME).app/Contents/MacOS/$(APP_NAME)"
	COPYFILE_DISABLE=1 tar -czf $(DIST_DIR)/mac/$(APP_NAME)-mac.tar.gz \
		-C $(DIST_DIR)/mac "$(APP_NAME).app"
	rm -rf "$(DIST_DIR)/mac/$(APP_NAME).app" $(DIST_DIR)/mac/$(APP_NAME)

build-windows: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --windowed --onefile --noconfirm --clean \
		--icon $(ICON) --add-data "$(ADD_DATA)" --add-data "$(ADD_TUTORIAL)" \
		--distpath $(DIST_DIR)/windows --workpath $(BUILD_DIR)/windows \
		$(ENTRY_POINT)

# The Linux binary ships as a tarball rather than a bare ELF file, because the
# executable bit does not survive the trip to a user's machine otherwise. Two
# separate things strip it: actions/upload-artifact zips without preserving Unix
# modes (so the `builds` branch ends up with 100644 blobs), and an HTTP download
# carries no permission metadata at all, so even a 100755 blob lands as 644 when
# fetched through GitHub's "Download raw file". A non-executable ELF doesn't run
# — GNOME Files reports "There is no app installed for Executable files" instead
# of launching it. tar records the mode inside the archive, so extracting yields
# a binary that is executable no matter how the archive travelled.
#
# Only the tarball is left in the dist directory: shipping the loose binary
# alongside it would just be a broken file for people to download by mistake.
build-linux: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --onefile --noconfirm --clean \
		--add-data "$(ADD_DATA)" --add-data "$(ADD_TUTORIAL)" \
		--distpath $(DIST_DIR)/linux --workpath $(BUILD_DIR)/linux \
		$(ENTRY_POINT)
	chmod +x $(DIST_DIR)/linux/$(APP_NAME)
	tar -czf $(DIST_DIR)/linux/$(APP_NAME)-linux.tar.gz \
		-C $(DIST_DIR)/linux $(APP_NAME)
	rm $(DIST_DIR)/linux/$(APP_NAME)

# --- PyPI distribution ------------------------------------------------------
#
# Unlike the PyInstaller builds above, the sdist and wheel are pure Python and
# platform-independent, so one machine (or one CI job) produces the artifacts
# everyone installs; PySide6 is left to pip to resolve per platform. The wheel
# is built from the sdist so that anything missing from the sdist shows up here
# rather than in a user's failed `pip install`.
#
# The release workflow (.github/workflows/release.yml) runs the same two steps
# on a version tag and uploads via PyPI trusted publishing, so `make publish` is
# only needed for a manual release — it prompts for a PyPI API token.

dist: install-publish
	rm -rf $(PYPI_DIR)
	$(PYTHON) -m build --outdir $(PYPI_DIR)
	$(VENV_BIN)/twine check --strict $(PYPI_DIR)/*

publish-test: dist
	$(VENV_BIN)/twine upload --repository testpypi $(PYPI_DIR)/*

publish: dist
	$(VENV_BIN)/twine upload $(PYPI_DIR)/*

# Convenience: build for whatever OS `make` is currently running on.
UNAME_S := $(shell uname -s 2>/dev/null)
ifeq ($(OS),Windows_NT)
build: build-windows
else ifeq ($(UNAME_S),Darwin)
build: build-mac
else
build: build-linux
endif
