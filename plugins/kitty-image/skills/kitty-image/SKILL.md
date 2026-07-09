---
name: kitty-image
description: Use when you want to show the user an actual image inline in the terminal — a photo, an image you fetched or downloaded, an existing image file or screenshot on disk, a chart/diagram/plot/figure you generated, or a workflow/flowchart/sequence/state/architecture diagram authored as a Mermaid definition. Any time the user wants to SEE something, asks what something looks like, asks you to diagram or visualize a workflow/process/flow, or a picture would communicate better than words, prefer obtaining the image and displaying it over describing it in prose. Renders real PNG/JPEG images via the Kitty graphics protocol, and renders Mermaid text to PNG via mermaid.py; requires the Kitty terminal (TERM=xterm-kitty) and fails with exit 2 otherwise. Do NOT use for ASCII/Unicode sparklines (those go in chat) or for saving an image to disk without displaying it. Also renders a web page or HTML (a live URL, a local .html file, or an HTML string) to an inline image via html.py (headless Chrome).
---

# kitty-image

Display real raster images (PNG/JPEG) inline in the user's active Claude Code Kitty terminal — even though the Bash tool has no controlling TTY and `kitty +kitten icat` therefore fails.

## When to invoke this skill

This is the way to put **any image** in front of the user in a Kitty terminal — not just data charts. Invoke whenever:
- The user asks to **see** something, or **what something looks like** — a place, animal, object, person, product, artwork. Show a real image instead of describing it in prose.
- The user points you at an **existing image file or screenshot** on disk and wants to view it.
- You produced an image yourself — a **chart, plot, diagram, flowchart, or figure** — that should appear inline.
- The user wants to **see a workflow, process, flowchart, sequence, state machine, or architecture** — author it as a **Mermaid** definition and render it with `mermaid.py` (see "Mermaid workflow diagrams" below). This is usually the fastest way to a clean diagram; reach for it before hand-drawing boxes in Pillow.
- The user wants to **see a web page, a URL, or a chunk of HTML** as it renders — use `html.py` (headless Chrome screenshot). Viewport by default; `--selector` for one element; `--full-page` for the whole page (shown scrolling, not shrunk).
- A **picture would communicate better than words** (distributions, comparisons, architecture sketches, anything visual).

### You obtain the image; this skill only displays it

kitty-image does **not** fetch or generate — it renders a PNG/JPEG you hand it. So when you don't already have a file, get one first:

- **Real-world photo/reference (puppy, landmark, product, etc.):** use a web **search** tool (e.g. firecrawl-search, WebSearch) to find a *real* image URL from the results, download it with `curl` to `/tmp`, then display it.
  - **Never invent, guess, or construct an image URL** — only ever use a URL that came back from an actual search/tool result. Searching for a real URL is exactly how you respect the "don't fabricate URLs" rule *and* still show the image. The rule forbids making URLs up; it does not forbid showing images.
  - If you genuinely have no web-search/fetch tool available, say so and ask the user for a file path or URL — don't fall back to a Pillow cartoon of a real thing.
- **Chart / data figure:** render it with Pillow or matplotlib to `/tmp`, then display it.
- **Workflow / flow / sequence / state / architecture diagram:** write a **Mermaid** definition and let `mermaid.py` render *and* display it in one step (it execs `show.py` for you). See "Mermaid workflow diagrams" below.

Don't let *"I don't have an image file"* stop you — obtaining the image is part of the job, not a reason to refuse.

Do **not** invoke for:
- Quick sparklines or tiny inline indicators where ASCII bars work fine
- Cases where `TERM` is not `xterm-kitty` (the skill fails with exit 2)
- Saving an image to disk without displaying it — just write the file
- Questions fully answerable in words where the user didn't want a visual

## How it works (one-paragraph mental model)

The Bash tool runs in a process with no controlling TTY, which is why `kitty +kitten icat` fails (`OSError: No such device or address: '/dev/tty'`). This skill bypasses that by walking the process tree to find the user's `claude` ancestor, reading its TTY from `/proc/<pid>/stat`, and writing Kitty graphics protocol escape sequences (`\x1b_G...\x1b\\`) directly to that PTY. Kitty intercepts the escapes at the terminal-emulator layer, before the claude TUI ever sees them.

**Unicode placeholders (the core trick).** `show.py` does *not* paint the image directly. Direct painting (`a=T` alone) anchors the image at the PTY cursor — which, during Claude Code's "Running" phase, sits at the bottom of the screen. The image ends up pinned below the prompt, clipped by the screen edge, and it never scrolls with the conversation. Instead `show.py` creates a **virtual placement** (`a=T,U=1,i=<id>`), which stores the image and draws nothing, then prints a grid of `U+10EEEE` placeholder cells to the tool's **stdout**. Each cell carries its row/column as combining diacritics and the image id as a 24-bit foreground colour; Kitty substitutes the image wherever those cells land. Because the cells are ordinary text, they live in Claude's committed transcript: the image appears exactly where the tool output is, and scrolls and packs with the conversation like any other text. Only the first cell of each row needs diacritics — Kitty auto-increments the column and reuses the row — which keeps a full-screen grid a few KB instead of tens of KB.

**Cell geometry (don't trust the PTY).** Sizing needs the terminal's per-cell pixel size, normally read from `TIOCGWINSZ`. Claude Code sets its own PTY's winsize with `ws_row`/`ws_col` populated and the **pixel fields left as garbage** (observed: `49049 x 65238` on a window whose real cell is `10 x 22`). A `ws_ypixel > 0` check does not catch this — the terminal doesn't stay silent, it lies. `plausible_cell()` therefore range-checks the derived cell (width 3–40px, height 6–80px, aspect 0.25–0.9); when our own PTY fails the check, `resolve_cell()` borrows the geometry from a sibling PTY of the same Kitty, since cell size is a property of the font, not the window. `DEFAULT_CELL` is the last resort. The chosen source is reported on stderr as `[cell geometry: pty|sibling|default]`.

**Fit-to-screen (oversized images).** `placement_cells()` returns a concrete `(cols, rows)` box, passed to Kitty as the `c=`/`r=` placement keys so it scales the image into that box. If the native size already fits the viewport it's returned unchanged (pixel-for-pixel); if it would overflow, both dimensions are scaled down by a single factor so the aspect ratio is preserved. Both dimensions are also capped at 297 cells — the number of addressable rows/columns in Kitty's diacritic table.

## Workflow

```
1. Generate or obtain the image (PNG preferred, JPEG works).
   - For charts: use Pillow (always available) or matplotlib if installed.
   - Save to /tmp/<descriptive>.png or similar.
2. Call: python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" <path>
3. Tell the user the image has been sent.
4. If the user wants the image cleared later:
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" --clear
```

`${CLAUDE_PLUGIN_ROOT}` is set by Claude Code to this plugin's install directory, so the path resolves wherever the plugin is installed.

## Caveats to communicate to the user

- **Placement is exact, and the image scrolls.** The placeholder cells *are* the image's position, so there is no drift, no overlap, and no reserved-blank-line heuristic. The image sits inline in the tool output and scrolls up out of view as the conversation grows — that is correct behaviour, not a bug. Scroll back to see it again.
- **Never swallow `show.py`'s stdout.** The placeholder grid is printed to stdout and *is* the rendered image. `show.py img.png > /dev/null` (or any caller that captures stdout) transmits the image to Kitty and then renders nothing at all. `mermaid.py` and `html.py` are safe: they inherit stdout via `subprocess.run(cmd)` without `capture_output`.
- **Requires Kitty >= 0.28** (0.29.1+ recommended, where the placeholder bugs were fixed). Unicode placeholders were introduced in 0.28; on older Kitty the cells render as literal garbage text instead of an image. The skill does not currently version-check — if you see rows of stray glyphs where an image should be, your Kitty is too old.
- **Images taller than the screen are scaled to fit.** `placement_cells()` downscales an oversized image (preserving aspect) to `ws_col - 1` × `ws_row - 2` cells, capped at 297 in each dimension, and hands Kitty the `c=`/`r=` keys to do the resampling. Pass `--scroll` to fit width only and leave the height uncapped, so a tall image scrolls at full detail instead of being shrunk.
- **Persistence.** The image stays until its placeholder cells scroll out of Kitty's scrollback, the user clears the screen, or `--clear` is invoked. `--clear` sends `a=d,d=A`, which deletes both placements *and* the stored image data — a bare `a=d` would leave virtual placements and image data resident in Kitty's memory.
- **Kitty-only.** This trick exploits the Kitty Graphics Protocol. It will not work in xterm, gnome-terminal, alacritty, or any terminal that doesn't speak that protocol. The skill checks `TERM=xterm-kitty` and refuses if it doesn't match.
- **Other Kitty-protocol terminals** (Ghostty, iTerm2, Konsole, Warp, WezTerm) *may* work if the user overrides with `--pts /dev/pts/N` and bypasses the TERM check, but this is untested.

## Common chart-rendering pattern (Pillow)

When the user asks for a chart and matplotlib isn't installed, fall back to Pillow:

```python
from PIL import Image, ImageDraw, ImageFont

W, H = 1100, 700
img = Image.new("RGB", (W, H), (16, 18, 26))   # dark BG; high contrast
d = ImageDraw.Draw(img)

def font(sz, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold \
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p, sz)

# ... render title, axes, grid, data marks ...

img.save("/tmp/chart.png")
```

Then invoke the skill:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" /tmp/chart.png
```

Design defaults that produce decent-looking charts:
- Dark background (`(16,18,26)`) with light foreground (`(235,236,240)`) — easy on the eyes, high contrast.
- Grid lines in a muted mid-tone (`(38,42,56)`) — visible but recessive.
- Data marks in saturated, distinct hues — keep at most 5–7 categorical colors.
- Always include: title, subtitle (data source + date range), axis labels, units, and a legend if categories are present.
- Use `DejaVuSans` (always installed on Debian/Ubuntu) at sizes 26 (title), 14 (subtitle), 13 (axis), 12 (ticks/labels).

## Mermaid workflow diagrams

For **workflows, flowcharts, sequence diagrams, state machines, ER/class diagrams, and architecture sketches**, don't hand-draw boxes in Pillow — write a [Mermaid](https://mermaid.js.org) definition and let `mermaid.py` render it to PNG *and* display it (it execs `show.py` for you, so all the text-overlap handling is reused).

```
1. Write the diagram to a .mmd file (use the Write tool — avoids shell-escaping
   multi-line text). Example /tmp/flow.mmd:

       graph TD
           A[Start] --> B{Renderer available?}
           B -->|local mmdc| C[Render offline]
           B -->|--remote| D[mermaid.ink]
           C --> E[Display via show.py]
           D --> E

2. Render + display in one call:
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/mermaid.py" /tmp/flow.mmd

3. Tell the user the diagram has been sent.
```

You can also pipe a diagram in: `... | mermaid.py -`.

### Keep inline diagrams compact and legible

A diagram is displayed *inline in the terminal*, so it is subject to fit-to-screen scaling. A tall diagram (many nodes top-to-bottom) gets downscaled hard to fit the viewport height, and the dark theme's thin light strokes can wash out at that reduction — it reads as a near-blank dark rectangle even though the PNG is fine. To keep diagrams sharp:

- **Prefer wide-and-short over tall-and-narrow.** Use `graph LR` (left→right) instead of `graph TD` when the flow is mostly linear, and keep it to a handful of nodes. A diagram that fits the viewport at native size needs no downscaling and stays crisp.
- **Split big flows** into a couple of smaller diagrams rather than one giant chart.
- If a tall diagram is unavoidable and looks washed out, tell the user it was downscaled and offer to render it `--no-show` to a PNG they can open at full size.

The diagram text is the payload — a workflow can encode internal architecture — so rendering is **local by default and never silently leaves the machine**:

- **Local (default):** uses `mmdc` if it's on `PATH`; otherwise falls back to
  `npx -p @mermaid-js/mermaid-cli mmdc` pointed at an already-installed Chrome
  (`google-chrome`, `chromium`, …) via a generated Puppeteer config, with
  `PUPPETEER_SKIP_DOWNLOAD=1` so Puppeteer never downloads its own ~150 MB Chromium.
  First `npx` run fetches mermaid-cli (~15–20 s); cached runs are ~2 s. Fully offline thereafter.
- **Remote (`--remote`, opt-in only):** renders via the public **mermaid.ink** service
  (pako-encoded URL, fetched as PNG). This **sends the diagram text to a third party**,
  so it only happens when *you* pass `--remote` — typically the fallback you offer the
  user when there's no local renderer (exit code 10).

### Options

```bash
mermaid.py <file>            # local render, dark theme, #10121a bg, 2x scale, then display
mermaid.py <file> --remote   # render via mermaid.ink instead (sends diagram offsite)
mermaid.py <file> --theme dark|default|forest|neutral
mermaid.py <file> --bg '#10121a'      # or a color name, or 'transparent'
mermaid.py <file> --scale 2           # local renderer only
mermaid.py <file> --out /tmp/x.png    # control output path
mermaid.py <file> --no-show           # render only; print the PNG path (e.g. for bg jobs)
mermaid.py <file> --pts /dev/pts/N    # passthrough to show.py
```

Defaults (`--theme dark`, `--bg '#10121a'`, `--scale 2`) match the Pillow chart aesthetic above, so mermaid diagrams sit consistently alongside generated charts.

## HTML & web page rendering

Render a **live URL, a local `.html` file, or an HTML string (stdin)** to a PNG
and display it inline with `html.py`. Like `mermaid.py`, it execs `show.py`, so
all the PTY/fit-to-screen handling is reused. It drives **Puppeteer-core pointed
at your system Chrome** — the same browser `mermaid.py` uses; puppeteer-core is
installed once into `${XDG_CACHE_HOME:-~/.cache}/kitty-image` and downloads no
Chromium.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" https://example.com
echo '<h1 style="font:48px sans-serif">hi</h1>' | python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" -
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" page.html --selector '.hero'
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/html.py" https://x.com --full-page
```

### Capture modes
- **Viewport (default):** the visible window at `--viewport WxH` (default `1280x800`). Best for inline display.
- **`--selector <css>`:** screenshot just the first matching element — crisp, ideal for one component.
- **`--full-page`:** the entire scroll height. Displayed via `show.py --scroll` (fit-to-width, **scrollable**, not shrunk to fit), so it stays readable. Defaults to `--scale 1` to keep the row count sane.

### Options
```
--viewport WxH   render viewport (default 1280x800)
--scale N        device scale factor (default 2; 1 for --full-page)
--wait MS        extra wait after network-idle (default 0)
--timeout MS     navigation/selector timeout (default 30000)
--out PATH       output PNG (default /tmp/html.png)
--no-show        render only; print the path
--pts /dev/pts/N passthrough to show.py
```

### Privacy & requirements
- **Local file / stdin render fully offline**; a **live URL** fetches that page (its whole point) and makes no other calls. There is **no third-party screenshot service**.
- Needs `node`/`npm` (already required by `mermaid.py`) and a system Chrome/Chromium **plus its OS libraries** (`libnss3`, `libgbm`, `libasound2`, …). These can't be auto-installed; on a bare server install them with your package manager. Exit codes: `20` no renderer/Chrome, `21` load failed, `22` selector not found, `23` bad input/output.
- For crisp inline output prefer viewport or `--selector`; `--full-page` is for scrolling through or saving with `--no-show`.

## Override and clear

```bash
# Force a specific PTY (if auto-detect fails or you want to target another tab)
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" /tmp/img.png --pts /dev/pts/4

# Clear all images currently on the active PTY
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" --clear
```

## Failure modes and what they mean

| Exit code | Source | Meaning | Fix |
|-----------|--------|---------|-----|
| 2 | show.py | Not running inside Kitty (`TERM != xterm-kitty`) | The skill cannot help; tell the user to open the file manually or use a Kitty-compatible terminal |
| 3 | show.py | No `claude` ancestor process found | The Bash environment is unusual (e.g. a background job); try `--pts` override, or render with `--no-show` and view the file another way |
| 4 | show.py | Detected PTY is not writable | Permission issue on `/dev/pts/<n>`; check ownership |
| 5 | show.py | Image file not found | Verify the path before calling the skill |
| 6 | show.py | Non-PNG input couldn't be converted (Pillow missing / unrecognized format) | Install `python3-pil`, or hand it a real PNG/JPEG |
| 10 | mermaid.py | No local mermaid renderer (`mmdc`, or `node`+Chrome) | Re-run with `--remote` to use mermaid.ink, or install mermaid-cli / a Chrome binary |
| 11 | mermaid.py | Local render failed (usually invalid Mermaid syntax) | mmdc's stderr is forwarded above; fix the diagram |
| 12 | mermaid.py | Remote render failed (network / service / non-PNG) | Check connectivity to mermaid.ink, or render locally |
| 13 | mermaid.py | Input diagram not found/empty, or output path not writable | Verify the `.mmd` path / that stdin had content / that `--out`'s directory is writable |
| 20 | html.py | No usable renderer — no `npm`/Node, or no Chrome/Chromium found | Install Node and a Chrome/Chromium (and its OS libs); see message |
| 21 | html.py | Navigation/load failed — bad URL, timeout, or missing local file | Check the URL/path and connectivity; raise `--timeout` |
| 22 | html.py | `--selector` element not found before timeout | Fix the selector or raise `--timeout` |
| 23 | html.py | Input/output error — empty stdin, or output dir not writable | Provide HTML on stdin / choose a writable `--out` |
