# scripts

`screenshots.py` regenerates the PNG files in `docs/images/` from real runs of the tool.

```
uv run scripts/screenshots.py
```

It needs `uv`, network or a warm uv cache, and a Playwright Chromium that matches
`playwright==1.62.0`. If Chromium is missing, run once:

```
uv run --with playwright==1.62.0 python -m playwright install chromium
```

The script rebuilds `/tmp/demo-api-reality-check` on every run (it deletes that directory first, but only if the directory holds the marker file that the script writes; otherwise it stops). It installs
pinned pandas, numpy and requests in a target venv, installs the tool from this clone in a
separate venv, runs the real commands, and renders terminal-style PNGs. It exits non-zero and
deletes the PNGs if any text contains `/home/`, `rajib`, `@gmail`, `github_pat_` or `ghp_`.
