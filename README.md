# Open Ansho (暗証) - Open-source qualitative data analysis

Open Ansho is a free and open-source desktop app for qualitative data analysis of text documents. This was designed as a fast and focused tool with the following goals:

- Fast coding: By using Vim-inspired keybindings, you can code a document without every moving your hands off the keyboard.
- Easy collaboration: No signup needed. All data (text and codes) are written to a database file that you can store in a shared directory (e.g., Dropbox, Google Drive, OneDrive).
- Clarity: Visually compare overlapping code segments through vertically-separated split highlights. Easily see simultaneous coding through striped segments.
- Lightweight: No bloat. Just fast coding.

This software was created using Claude Code.

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
