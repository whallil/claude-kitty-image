---
name: kitty-image
description: Use when you want to show the user an actual image inline in the terminal — a photo, an image you fetched or downloaded, an existing image file or screenshot on disk, a chart/diagram/plot/figure you generated, or a workflow/flowchart/sequence/state/architecture diagram authored as a Mermaid definition. Any time the user wants to SEE something, asks what something looks like, asks you to diagram or visualize a workflow/process/flow, or a picture would communicate better than words, prefer obtaining the image and displaying it over describing it in prose. Renders real PNG/JPEG images via the Kitty graphics protocol, and renders Mermaid text to PNG via mermaid.py; requires the Kitty terminal (TERM=xterm-kitty) and fails with exit 2 otherwise. Do NOT use for ASCII/Unicode sparklines (those go in chat) or for saving an image to disk without displaying it.
---

# kitty-image

Display real raster images (PNG/JPEG) inline in the user's active Claude Code Kitty terminal — even though the Bash tool has no controlling TTY and `kitty +kitten icat` therefore fails.

## When to invoke this skill

This is the way to put **any image** in front of the user in a Kitty terminal — not just data charts. Invoke whenever:
- The user asks to **see** something, or **what something looks like** — a place, animal, object, person, product, artwork. Show a real image instead of describing it in prose.
- The user points you at an **existing image file or screenshot** on disk and wants to view it.
- You produced an image yourself — a **chart, plot, diagram, flowchart, or figure** — that should appear inline.
- The user wants to **see a workflow, process, flowchart, sequence, state machine, or architecture** — author it as a **Mermaid** definition and render it with `mermaid.py` (see "Mermaid workflow diagrams" below). This is usually the fastest way to a clean diagram; reach for it before hand-drawing boxes in Pillow.
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

The Bash tool runs in a process with no controlling TTY, which is why `kitty +kitten icat` fails (`OSError: No such device or address: '/dev/tty'`). This skill bypasses that by walking the process tree to find the user's `claude` ancestor, reading its TTY from `/proc/<pid>/stat`, and writing Kitty graphics protocol escape sequences (`\x1b_G...\x1b\\`) directly to that PTY. Kitty intercepts the escapes at the terminal-emulator layer and renders the image into its image plane, on top of the text grid that the claude TUI is drawing. The image persists through claude's normal redraws because it lives on a separate render layer.

**Avoiding text overlap (important).** The image lives on Kitty's graphics layer, which Claude Code's renderer knows nothing about — so by default Claude packs its subsequent text right over the image's rows. Newlines written to the PTY don't help: Claude repaints from its own screen model and discards them. The fix is to reserve real vertical space in the one channel Claude *does* commit — the tool's **stdout**. `show.py` computes the image's cell box (`placement_cells()`: PNG pixel size ÷ the PTY's per-cell pixel size from `TIOCGWINSZ`) and prints that many blank lines to stdout, so Claude reserves genuine rows that scroll and pack with the conversation. Two wrinkles are handled: the image anchors a few rows below the reserved block (it's drawn during the "Running" phase while stdout lays out afterward), so a `DRIFT_MARGIN` over-reserves to absorb the offset; and a trailing caption line (`└─ <filename>`) prevents the blank rows from being trimmed as trailing whitespace.

**Fit-to-screen (oversized images).** `placement_cells()` returns a concrete `(cols, rows)` box, which `show.py` passes as the Kitty `c=`/`r=` placement keys so Kitty scales the image into that box. If the native size already fits the viewport it's returned unchanged (pixel-for-pixel); if it would overflow, both dimensions are scaled down by a single factor so the aspect ratio is preserved. The box leaves one column of horizontal headroom (no wrap) and `DRIFT_MARGIN + 2` rows of vertical headroom, so a downscaled image plus its anchor offset still fit on one screen rather than clipping at the bottom.

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

- **Text overlap is handled, with a margin.** The skill reserves vertical space sized to the image (see "Avoiding text overlap" above), so following text lands below the image rather than on top of it. The reservation includes a fixed `DRIFT_MARGIN` (currently 6 rows) to absorb the offset between the image anchor and the stdout block. This is a heuristic tuned to the skill's normal one-line invocation — if the command echo is unusually tall (e.g. a very long image path that wraps), the drift can grow and a couple of rows of overlap may reappear.
- **Vertical placement is approximate.** Height (row count) is matched exactly, but the image's *start row* can drift by a few rows: it's painted at the PTY cursor during the "Running" phase while Claude Code lays out the committed stdout block independently, and the exact offset between the two is scroll/timing-dependent and partly controlled by Claude's renderer. Expect a small, usually-harmless top or bottom gap; it is not pixel-stable.
- **Images taller than the screen are scaled to fit.** `placement_cells()` downscales an oversized image (preserving aspect) to `ws_col - 1` × `ws_row - 2 - DRIFT_MARGIN` cells and hands Kitty the `c=`/`r=` keys to do the resampling, so tall or huge images no longer overflow onto following text. Trade-off: a very tall image is shrunk to fit the current window height, so a shorter terminal yields a smaller image — resize the window taller (or open the file externally) if you need more detail.
- **Persistence.** The image stays on screen until Kitty scrolls it out of viewport, the user clears the screen, or `--clear` is invoked. Claude Code redraws do NOT remove it.
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
