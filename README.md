# Open Ansho (暗証) - Open-source qualitative data analysis

Open Ansho is a free and open-source desktop app for qualitative data analysis of text documents. This was designed as a fast and focused tool with the following goals:

- Fast coding: By using Vim-inspired keybindings, you can code a document without ever moving your hands off the keyboard.
- Easy collaboration: No signup needed. All data (text and codes) are written to a database file that you can store in a shared directory (e.g., Dropbox, Google Drive, OneDrive).
- Clarity: Visually compare overlapping code segments through vertically-separated split highlights. Easily see simultaneous coding through striped segments.
- Lightweight: No bloat. Just fast coding.

This software was created using Claude Code.

## Download and Run

Prebuilt executables for macOS, Windows, and Linux are published on the [`builds` branch](https://github.com/zdelrosario/open-ansho/tree/builds/runs). Each build lives in its own folder named `<run number>-<commit>`; open the highest-numbered one for the most recent build, then the folder for your operating system.

The app is fully self-contained — there is nothing to install, and no Python needed. On Windows and Linux, expect a few seconds of delay every time you start it: those builds are a single file that unpacks itself to a temporary directory on each launch. The macOS app is a normal bundle and starts without that pause.

These builds are not code-signed, so each operating system will warn you the first time you open one. The steps below include how to get past that. If you would rather not click through a security warning, run from source instead — see [Development Setup](#development-setup).

> **Tip:** OpenAnsho remembers your username in a `.openansho_user` file it writes alongside the executable (inside the app bundle, on macOS). Put the app somewhere permanent and writable — `~/Applications` on macOS, a folder under your user account such as `C:\Users\<you>\Apps` on Windows — rather than leaving it in `Downloads`. Avoid `C:\Program Files`, which a standard account cannot write to. Replacing the app with a newer build starts you over with a fresh username file.

### Windows

1. Download `OpenAnsho.exe` from the `windows` folder.
2. Double-click it.
3. Windows SmartScreen will likely say it "protected your PC". Click **More info**, then **Run anyway**.

### macOS

1. Download `OpenAnsho-mac.tar.gz` from the `mac` folder.
2. Double-click the archive to extract `OpenAnsho.app`, then drag it to your Applications folder.
3. Double-click the app. macOS will refuse to open it, saying the developer cannot be verified.
4. Open **System Settings → Privacy & Security**, scroll to the Security section, and click **Open Anyway** next to the message about OpenAnsho. Confirm once more when prompted.

You only need to do step 4 once. On older versions of macOS you can instead right-click the app and choose **Open**, which offers an **Open** button in the warning dialog; recent versions have removed that shortcut for unsigned apps in favor of the Privacy & Security panel.

### Linux

1. Download `OpenAnsho-linux.tar.gz` from the `linux` folder.
2. Extract it and run the binary:

```bash
tar -xzf OpenAnsho-linux.tar.gz
./OpenAnsho
```

The binary inside the archive is already marked executable, so no `chmod` is needed. Extract it with `tar` rather than dragging it out of an archive viewer, since some viewers drop file permissions — if you end up with a file that won't start, `chmod +x OpenAnsho` restores it.

The Linux build is produced on the current Ubuntu CI image, so it needs a reasonably recent glibc and will not run on notably older distributions. It also unpacks itself into `/tmp` at startup, which fails on systems that mount `/tmp` with `noexec`; setting `TMPDIR` to a directory that permits execution works around that.

## Development Setup

First-time setup, run once from the repo root:

```bash
python3 -m venv .venv           # create the project virtualenv
source .venv/bin/activate       # activate it
pip install -e ".[dev]"        # install package + dev deps (pytest, pytest-qt)
```

Every subsequent session, activate the virtualenv before running any commands below:

```bash
source .venv/bin/activate       # activate the project virtualenv
```

To run the development version of the app (with the virtualenv active):

```bash
python -m openansho              # run the app (or the `openansho` console script)
```

## Learning Vim

While the app can be used using traditional controls (mouse and keyboard), you'll get the most out of Open Ansho if you learn how to navigate using Vim keybindings. There are a variety of interactive tutorials for learning Vim, such as [VimHero](https://www.vim-hero.com/), [VIM Adventures](https://vim-adventures.com/), and [OpenVim](https://openvim.com/).
