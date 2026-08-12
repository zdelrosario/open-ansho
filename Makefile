# Makefile for building the OpenAnsho desktop app with PyInstaller.
#
# PyInstaller does not cross-compile: it can only build an executable for
# the OS it runs on. So build-mac must run on macOS, build-windows on
# Windows, and build-linux on Linux (e.g. as separate jobs in a CI matrix).
# `make build` builds for whichever platform you're currently on.

APP_NAME := OpenAnsho
ENTRY_POINT := src/openansho/__main__.py
ICON := images/kanji_shou_app_icon.png
DIST_DIR := dist
BUILD_DIR := build
VENV := .venv

ifeq ($(OS),Windows_NT)
    VENV_BIN := $(VENV)/Scripts
    SYSTEM_PYTHON := python
    ADD_DATA := $(ICON);images
else
    VENV_BIN := $(VENV)/bin
    SYSTEM_PYTHON := python3
    ADD_DATA := $(ICON):images
endif

PYTHON := $(VENV_BIN)/python
PIP := $(VENV_BIN)/pip
PYINSTALLER := $(VENV_BIN)/pyinstaller
PYTEST := $(VENV_BIN)/pytest

.PHONY: help venv install install-build test clean build build-mac build-windows build-linux

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
	@echo "  clean          Remove build/dist artifacts and .spec files"

$(VENV_BIN)/python:
	$(SYSTEM_PYTHON) -m venv $(VENV)

venv: $(VENV_BIN)/python

install: venv
	$(PIP) install -e ".[dev]"

install-build: venv
	$(PIP) install -e ".[build]"

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
# macOS stays one-dir: --windowed there produces a .app bundle, which already
# travels as one object in Finder and in a zip.

build-mac: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --windowed --noconfirm --clean \
		--icon $(ICON) --add-data "$(ADD_DATA)" \
		--distpath $(DIST_DIR)/mac --workpath $(BUILD_DIR)/mac \
		$(ENTRY_POINT)

build-windows: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --windowed --onefile --noconfirm --clean \
		--icon $(ICON) --add-data "$(ADD_DATA)" \
		--distpath $(DIST_DIR)/windows --workpath $(BUILD_DIR)/windows \
		$(ENTRY_POINT)

build-linux: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --onefile --noconfirm --clean \
		--add-data "$(ADD_DATA)" \
		--distpath $(DIST_DIR)/linux --workpath $(BUILD_DIR)/linux \
		$(ENTRY_POINT)

# Convenience: build for whatever OS `make` is currently running on.
UNAME_S := $(shell uname -s 2>/dev/null)
ifeq ($(OS),Windows_NT)
build: build-windows
else ifeq ($(UNAME_S),Darwin)
build: build-mac
else
build: build-linux
endif
