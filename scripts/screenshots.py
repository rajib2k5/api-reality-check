# /// script
# requires-python = ">=3.10"
# dependencies = ["rich==14.2.0", "playwright==1.62.0"]
# ///
"""Regenerate the how-to-use screenshots in docs/images/ from real runs of the tool.

Run from anywhere:

    uv run scripts/screenshots.py

First run only, if Chromium is missing:

    uv run --with playwright==1.62.0 python -m playwright install chromium

What it does:
  1. Recreates /tmp/arc-demo (neutral dir). Builds /tmp/arc-demo/.venv (target libraries: pandas, numpy,
     requests, pinned) and /tmp/arc-demo/tool (api-reality-check installed from this repo).
  2. Writes short demo files, runs the REAL commands with cwd=/tmp/arc-demo, HOME=/tmp/arc-demo,
     USER=demo and relative arguments, and captures stdout+stderr and exit codes.
  3. Renders each session as a terminal frame (rich SVG), then converts it to PNG with
     headless Chromium (Playwright).
  4. Scans every captured text, SVG and PNG for private strings. Exits non-zero on a hit.

Nothing on the screenshots is typed by hand: the displayed command is the string that runs,
and the output is what it printed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI
from rich.text import Text

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "images"
DEMO = Path("/tmp/arc-demo")
SVG_DIR = DEMO / "svg"
LIBS = ["pandas==3.1.0", "numpy==2.5.4", "requests==2.34.2"]
FORBIDDEN = ["/home/", "rajib", "@gmail", "github_pat_", "ghp_"]
WIDTH = 100  # terminal columns; keep wide enough to avoid wrapping of tool output

APP_PY = '''import pandas as pd
import numpy as np

df = pd.read_csv("prices.csv", index_coll=0)
df["ret"] = df["close"].pct_change()
grid = np.linspce(0, 1, 5)
print(df.head(), grid)
'''

CLEAN_PY = '''import pandas as pd
import numpy as np
import requests

df = pd.read_csv("prices.csv", index_col=0, parse_dates=True)
df["ret"] = df["close"].pct_change()
grid = np.linspace(0, 1, 5)
r = requests.get("https://example.com", timeout=5)
print(df.head(), grid, r.status_code)
'''

KWARGS_PY = '''import requests

r = requests.get("https://example.com", timout=5)
s = requests.post("https://example.com/api", jsn={"a": 1})
print(r.status_code, s.status_code)
'''

HOOK_PY = '''import pandas as pd
import numpy as np

df = pd.read_csv("prices.csv", index_coll=0)
df["ret"] = df["close"].pct_change()
grid = np.linspce(0, 1, 5)
'''

PAYLOAD = (
    '{"hook_event_name":"PostToolUse","tool_name":"Write",'
    '"tool_input":{"file_path":"/tmp/arc-demo/project/app.py"},"cwd":"/tmp/arc-demo/project"}'
)

HOOK_CMD = (
    "CLAUDE_PLUGIN_ROOT=/tmp/arc-demo/plugins/api-reality-check "
    "CLAUDE_PROJECT_DIR=/tmp/arc-demo/project "
    "API_REALITY_CHECK_PYTHON=/tmp/arc-demo/.venv/bin/python "
    "python3 -I -S -B plugins/api-reality-check/hooks/run_hook.py < payload.json > out.json"
)

# Each shot: (png name, window title, [(command, show exit code)]).
SHOTS = [
    ("01-install.png", "api-reality-check: install check", [
        ("api-reality-check --version", False),
        ("api-reality-check --help | head -n 12", False),
    ]),
    ("02-missing.png", "api-reality-check: hallucinated names", [
        ("cat -n app.py", False),
        ("api-reality-check --python .venv/bin/python app.py", True),
    ]),
    ("03-clean.png", "api-reality-check: clean file", [
        ("cat -n clean.py", False),
        ("api-reality-check --python .venv/bin/python clean.py", True),
    ]),
    ("04-show-unknown.png", "api-reality-check: --show-unknown", [
        ("cat -n kwargs.py", False),
        ("api-reality-check --python .venv/bin/python kwargs.py", True),
        ("api-reality-check --python .venv/bin/python --show-unknown kwargs.py", True),
    ]),
    ("05-hook.png", "api-reality-check: Claude Code PostToolUse hook", [
        ("cat -n project/app.py", False),
        (f"echo '{PAYLOAD}' > payload.json", False),
        (HOOK_CMD, True),
        ("python3 -m json.tool --no-ensure-ascii out.json", False),
    ]),
]

# Environment for every demo command: no real HOME, USER or PATH entries from this machine.
DEMO_ENV = {
    "HOME": "/tmp/arc-demo",
    "USER": "demo",
    "LOGNAME": "demo",
    "PS1": "$ ",
    "PATH": "/tmp/arc-demo/tool/bin:/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "COLUMNS": str(WIDTH),
}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)


def setup() -> None:
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    run(["uv", "venv", "--python", "3.12", str(DEMO / ".venv")])
    run(["uv", "pip", "install", "--python", str(DEMO / ".venv/bin/python"), *LIBS])
    run(["uv", "venv", str(DEMO / "tool")])
    run(["uv", "pip", "install", "--python", str(DEMO / "tool/bin/python"), str(REPO)])
    plugin = DEMO / "plugins" / "api-reality-check"
    plugin.mkdir(parents=True)
    for name in (".claude-plugin", "hooks", "src"):
        shutil.copytree(REPO / name, plugin / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    (DEMO / "project").mkdir()
    (DEMO / "app.py").write_text(APP_PY)
    (DEMO / "clean.py").write_text(CLEAN_PY)
    (DEMO / "kwargs.py").write_text(KWARGS_PY)
    (DEMO / "project" / "app.py").write_text(HOOK_PY)


def capture(cmd: str) -> tuple[str, int]:
    p = subprocess.run(["bash", "--noprofile", "--norc", "-c", cmd], cwd=DEMO, env=DEMO_ENV,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
    return p.stdout, p.returncode


STYLES = [(r"\bMISSING\b", "bold red"), (r"\bUNKNOWN\b", "bold yellow"),
          (r"\bSUSPECT\b", "bold magenta"), (r"^OK\b", "bold green")]


def render(title: str, steps, captured: list[str]) -> str:
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor",
                      file=open("/dev/null", "w"))
    for cmd, show_exit in steps:
        lines = cmd.split("\n")
        console.print(Text("$ ", style="bold green") + Text(lines[0]))
        out, rc = capture(cmd)
        captured.append(cmd)
        captured.append(out)
        if out:
            t = Text(out.rstrip("\n"))
            for pat, style in STYLES:
                t.highlight_regex(pat, style)
            console.print(t, soft_wrap=False)
        if show_exit:
            console.print(Text("$ ", style="bold green") + Text("echo $?"))
            console.print(Text(str(rc)))
            captured.append(str(rc))
        console.print()
    return console.export_svg(title=title, theme=MONOKAI)


def svg_to_png(svg_path: Path, png_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    svg = svg_path.read_text()
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    w, h = int(float(m.group(1))) + 1, int(float(m.group(2))) + 1
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1.5)
        page.goto(svg_path.as_uri())
        page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": w, "height": h})
        browser.close()


def scan(label: str, data: bytes | str) -> list[str]:
    raw = data if isinstance(data, bytes) else data.encode()
    return [f"{label}: found {bad!r}" for bad in FORBIDDEN if bad.encode() in raw]


def main() -> int:
    setup()
    SVG_DIR.mkdir()
    OUT.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    for png, title, steps in SHOTS:
        captured: list[str] = []
        svg = render(title, steps, captured)
        svg_path = SVG_DIR / png.replace(".png", ".svg")
        svg_path.write_text(svg)
        svg_to_png(svg_path, OUT / png)
        problems += scan(f"{png} captured text", "\n".join(captured))
        problems += scan(f"{png} svg", svg)
        problems += scan(f"{png} png bytes", (OUT / png).read_bytes())
        print(f"{png}: {(OUT / png).stat().st_size} bytes")
    if problems:
        print("PRIVATE DATA FOUND:", *problems, sep="\n  ", file=sys.stderr)
        for png, _, _ in SHOTS:
            (OUT / png).unlink(missing_ok=True)
        return 1
    print("scan clean: none of", FORBIDDEN, "found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
