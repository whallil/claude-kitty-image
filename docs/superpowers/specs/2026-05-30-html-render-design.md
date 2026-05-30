# Design: `html.py` — render HTML to an inline image (v0.4.0)

## Summary

Add an `html.py` to the kitty-image skill that renders **a live URL, a local HTML
file, or a raw HTML string (stdin)** to a PNG and displays it inline, reusing
`show.py` for display. It drives **Puppeteer-core pointed at the user's
already-installed Chrome** — the same browser `mermaid.py` relies on, so users
need no new browser. Puppeteer-core is installed once into a small user cache
dir via `npm install --prefix` (validated: ~1s, 26 packages, **downloads no
Chromium**); the script then runs with `NODE_PATH` pointing at that cache.

Three capture modes: **viewport** (default), **single element by CSS selector**,
and **full page**. Full-page introduces a new display mode in `show.py`:
**fit-to-width with uncapped, scrollable height** (rather than shrinking the whole
page to fit the screen, which would render it illegible).

## Goals

- Render URL / local file / stdin HTML to PNG and display inline via `show.py`.
- Three capture modes: viewport (default), `--selector <css>`, `--full-page`.
- Zero new *browser* install: reuse system Chrome (puppeteer-core never
  downloads one), mirroring `mermaid.py`'s Chrome handling. The only fetch is a
  one-time ~1s `npm install` of puppeteer-core into a user cache.
- Full-page captures display at readable size and **scroll**, instead of being
  downscaled to a washed-out thumbnail.

## Non-goals

- **No remote screenshot fallback.** Unlike `mermaid.ink`, there is no
  third-party rendering service: it would send the URL/HTML offsite and is
  unreliable. Local rendering only (live URLs obviously still fetch the page).
- **No Markdown→image path** (could be a future, separate feature).
- **No auto-installing Chrome or its OS libraries.** If no usable Chrome is
  found, exit with a clear, dedicated error telling the user what to install.
- No device-emulation presets, cookie/auth injection, or PDF output (YAGNI;
  revisit if requested).

## Architecture

A new **`html.py`** sibling to `show.py` / `mermaid.py`, following the same
shape: **render → exec `show.py`**, so all of `show.py`'s PTY detection,
fit-to-screen, and text-overlap handling is reused unchanged.

New / changed files (all under `plugins/kitty-image/skills/kitty-image/`):

1. **`html.py`** *(new)* — Python CLI/wrapper. Resolves the input source,
   validates args, invokes the Puppeteer script, maps failures to exit codes,
   and hands the PNG to `show.py` (with `--scroll` for full-page).
2. **`_snap.js`** *(new)* — a small, readable Puppeteer-core script that does the
   actual navigate + screenshot. A bundled `.js` file is preferred over a
   `node -e` string for readability and maintainability. (`mermaid.py` needed no
   JS because `mmdc` *is* the binary; arbitrary HTML needs real Puppeteer.)
3. **`_chrome.py`** *(new; targeted refactor)* — extract the helpers currently
   living in `mermaid.py` so both scripts share one copy:
   `CHROME_CANDIDATES`, `find_chrome()`, `write_puppeteer_config()`,
   `PNG_MAGIC`, `is_png()`, and `display()` (exec `show.py`). `mermaid.py` is
   updated to import from `_chrome.py`; its behavior is unchanged.
4. **`show.py`** *(changed)* — add a `--scroll` display mode (fit width, uncapped
   height). See "show.py changes".

### Data flow

```
source (URL | file | '-')
      │  html.py: resolve to a navigable URL
      │    '-'      -> read stdin -> temp .html -> file://<abs>
      │    http(s)  -> use as-is
      │    file     -> file://<abs>  (missing file -> exit 21)
      ▼
_chrome.py.find_chrome()  ──none──> exit 20 (clear "install Chrome" message)
      │ chrome path
      ▼
ensure puppeteer-core in cache  ──no npm──> exit 20
      │    if not <cache>/node_modules/puppeteer-core:
      │       npm install --prefix <cache> --no-save --no-audit --no-fund puppeteer-core
      ▼
node _snap.js   (env: NODE_PATH=<cache>/node_modules, SNAP_CFG=<json>)
      │    launch(executablePath=<chrome>, args=[--no-sandbox,--disable-gpu], headless:true)
      │    page.setViewport({width,height,deviceScaleFactor:scale})
      │    page.goto(url, {waitUntil:'networkidle2', timeout})
      │    [--wait ms] optional fixed delay
      │    capture:
      │      default     -> page.screenshot({path:out})
      │      --full-page -> page.screenshot({path:out, fullPage:true})
      │      --selector  -> waitForSelector(sel,{timeout}); el.screenshot({path:out})
      ▼
out.png  ──(unless --no-show)──> show.py out [--scroll if --full-page] [--pts]
```

## CLI surface

```
html.py <source>                      # URL (http/https), file path, or '-' for stdin HTML
html.py https://example.com
echo '<h1 style=...>hi</h1>' | html.py -
html.py page.html --selector '.hero'  # screenshot one element (waits for it)
html.py https://x.com --full-page     # whole page; displays fit-to-width, scrolls
html.py <src> --viewport 1280x800     # viewport size (default 1280x800)
html.py <src> --scale 2               # deviceScaleFactor (default 2; full-page default 1)
html.py <src> --wait 500              # extra ms after networkidle (default 0)
html.py <src> --timeout 30000         # nav / selector timeout ms (default 30000)
html.py <src> --out /tmp/x.png        # output path (default /tmp/<name>.png)
html.py <src> --no-show               # render only; print path
html.py <src> --pts /dev/pts/N        # passthrough to show.py
```

### Source resolution
- `-` → read stdin → write temp `.html` → navigate `file://<abs>`.
- starts with `http://` or `https://` → use as-is.
- otherwise treat as a filesystem path; if it exists → `file://<abs>`; if not →
  exit 21 (do not guess that an arbitrary string is HTML).

### Argument rules
- `--full-page` and `--selector` are mutually exclusive → usage error (exit 2).
- `--viewport` must match `<int>x<int>`, both > 0 → usage error otherwise.
- `--scale` positive integer. Default 2; when `--full-page` and the user did not
  pass `--scale`, default to **1** (keeps full-page row counts sane).
- `--full-page` implies `show.py --scroll` at display time.

## show.py changes

Add a `--scroll` flag selecting **fit-to-width** placement instead of the
default fit-to-screen. Implemented by parameterizing the existing
`placement_cells()`:

```
placement_cells(tty_fd, png_bytes, fit_height=True)
  nat_c, nat_r = ceil(img_px / cell_px)            # native cell size
  avail_c = ws_col - 1                             # terminal width is the MAX, not a target
  if fit_height:                                   # DEFAULT (v0.3.0 behavior)
      avail_r = ws_row - 2 - DRIFT_MARGIN
      if fits both -> (nat_c, nat_r)
      else scale by min(avail_c/nat_c, avail_r/nat_r)
  else:                                            # --scroll : fit width only
      if nat_c <= avail_c -> (nat_c, nat_r)        # native; NOT stretched to full width; height uncapped
      else scale = avail_c / nat_c -> (avail_c, round(nat_r*scale))  # only DOWNscale; height uncapped
```

**Width is never upscaled.** A capture narrower than the terminal stays at its
native width — it is *not* stretched to 100% of the terminal — because upscaling
a raster screenshot blurs it without adding legibility. The terminal width is
only an upper bound: we downscale a too-wide capture to fit, never enlarge a
small one. Height is always left uncapped so the page scrolls.

Row reservation in `main()` is unchanged (`rows + DRIFT_MARGIN`); in `--scroll`
mode `rows` is simply not capped at screen height, so the blank reservation can
exceed one screen and the image scrolls with the conversation exactly like long
text output. The `c=`/`r=` keys are still emitted so Kitty does the resampling.

This is a backward-compatible addition: default behavior (no `--scroll`) is
byte-for-byte the current v0.3.0 path.

### Readability is set at render time

Because width is never upscaled, legibility of a full-page capture is governed by
the **render viewport width**, not by display stretching. `html.py --full-page`
therefore captures at the `--viewport` width (default 1280px) so text renders at
a readable size and the result is shown at native width (scrolling vertically).
A user who wants a narrower, more book-like column can pass a smaller
`--viewport` (e.g. `800x600`); a very wide terminal will *not* blow the page up
to fill it.

## Error handling / exit codes

Distinct range from `mermaid.py`'s 10–13 to keep diagnostics unambiguous:

| Code | Meaning |
|------|---------|
| 0  | success |
| 2  | usage error (argparse: bad flags, viewport format, full-page+selector) |
| 20 | no usable renderer — `npm`/Node missing, or no Chrome/Chromium found (message lists candidates + how to install) |
| 21 | navigation/load failed — bad URL, network error, timeout, or missing local `file://` |
| 22 | `--selector` element not found before timeout |
| 23 | input/output error — empty stdin, or output path/dir not writable |
| 2–6 | `show.py`'s own codes propagate when the display step runs |

`_snap.js` exits non-zero with a short reason on failure; `html.py` maps the
Puppeteer failure class (navigation vs selector) to 21/22, forwarding stderr.

## Privacy

- **Local file / stdin HTML:** fully offline. Nothing leaves the machine.
- **Live URL:** fetches that page (the whole point); no *other* network calls.
- No third-party screenshot service. Documented in SKILL.md.

## Testing

The repo has no test suite yet; add a small `tests/` (pytest):

- **Unit (no browser needed):**
  - source resolution: `http(s)://` passthrough; existing file → `file://<abs>`;
    missing file → exit 21; `-` → stdin path.
  - `--viewport` parsing/validation (`1280x800` → `(1280,800)`; bad → exit 2).
  - `find_chrome()` with monkeypatched `shutil.which` (found / not-found → 20).
  - arg conflict: `--full-page` + `--selector` → exit 2.
  - `placement_cells(..., fit_height=False)`: width-fit, height uncapped;
    `fit_height=True` unchanged (regression guard for v0.3.0).
- **Integration (smoke):** render a tiny local HTML file to PNG and assert PNG
  magic + plausible dimensions; auto-`skip` when `npm`/Node or Chrome is absent
  so CI without a browser still passes.

## Docs & version

- `plugin.json` version → **0.4.0**.
- `SKILL.md`: new "HTML & web page rendering" section (the three inputs, three
  capture modes, `--full-page` scroll behavior); a when-to-invoke bullet; and
  caveats — live-URL privacy, requires system Chrome **and its OS libraries**
  (`libnss3`, `libgbm`, …; can't be auto-installed), and prefer viewport/selector
  for crisp inline output (full-page is for scrolling/saving).
- `README.md` feature list + `CHANGELOG.md` `[0.4.0]`.

## Resolved during design (spike on 2026-05-30)

- **Module resolution — RESOLVED.** `npx -p puppeteer-core node _snap.js` does
  *not* make `require('puppeteer-core')` resolvable (`-p` only exposes bins). The
  working mechanism, verified end-to-end, is: `npm install --prefix <cache>
  puppeteer-core` (once), then run `node _snap.js` with
  `NODE_PATH=<cache>/node_modules`. Install was ~1s / 26 packages with **no
  Chromium download**. All three capture modes produced correct PNGs against
  system Chrome (viewport 1800×1200, full-page 1800×3196, selector 1332×496 at
  `--viewport 900x600 --scale 2`).
- **Cache location:** `${XDG_CACHE_HOME:-~/.cache}/kitty-image/node_modules`
  (writable; the plugin install dir is version-pinned/possibly read-only).
- **First-run cost:** one ~1s `npm install` if the cache is empty; instant after.
  Requires `npm` on PATH (ships with the Node `mermaid.py` already needs).
