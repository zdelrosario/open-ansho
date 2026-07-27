# Makefile for building the OpenAnsho desktop app with PyInstaller.
#
# PyInstaller does not cross-compile: it can only build an executable for
# the OS it runs on. So build-mac must run on macOS, build-windows on
# Windows, and build-linux on Linux (e.g. as separate jobs in a CI matrix).
# `make build` builds for whichever platform you're currently on.

APP_NAME := OpenAnsho
ENTRY_POINT := src/openansho/__main__.py
DIST_DIR := dist
BUILD_DIR := build
VENV := .venv

ifeq ($(OS),Windows_NT)
    VENV_BIN := $(VENV)/Scripts
    SYSTEM_PYTHON := python
else
    VENV_BIN := $(VENV)/bin
    SYSTEM_PYTHON := python3
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

build-mac: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --windowed --noconfirm --clean \
		--distpath $(DIST_DIR)/mac --workpath $(BUILD_DIR)/mac \
		$(ENTRY_POINT)

build-windows: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --windowed --noconfirm --clean \
		--distpath $(DIST_DIR)/windows --workpath $(BUILD_DIR)/windows \
		$(ENTRY_POINT)

build-linux: install-build
	$(PYINSTALLER) --name "$(APP_NAME)" --noconfirm --clean \
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
