---
name: kitty-image
description: Display a PNG or JPEG image inline in the user's active Claude Code session running inside the Kitty terminal. Use this whenever the user asks for a chart, graph, plot, diagram, screenshot rendering, or any other visual that should appear inline in the chat. Bypasses the limitation that `kitty +kitten icat` cannot run from Claude Code's Bash tool (no controlling TTY) by injecting Kitty graphics protocol escape sequences directly into the user's PTY. ONLY works when the user is running Claude Code inside Kitty (TERM=xterm-kitty); will fail loudly with exit code 2 otherwise. Do NOT use for ASCII/Unicode block-character "graphs" — those go directly in the chat. Do NOT use outside Kitty.
---

# kitty-image

Display real raster images (PNG/JPEG) inline in the user's active Claude Code Kitty terminal — even though the Bash tool has no controlling TTY and `kitty +kitten icat` therefore fails.

## When to invoke this skill

Invoke whenever the user asks for any of:
- A chart, graph, plot, dashboard, or data visualization
- A diagram, flowchart, or rendered architecture sketch
- A screenshot or image to be shown inline (not just saved to disk)
- Any visual output where ASCII/Unicode block characters would be inadequate

Do **not** invoke for:
- Quick sparklines or tiny inline indicators where ASCII bars work fine
- Cases where `TERM` is not `xterm-kitty` (the skill will fail with exit 2)
- Saving images to disk without displaying them — just write the file

## How it works (one-paragraph mental model)

The Bash tool runs in a process with no controlling TTY, which is why `kitty +kitten icat` fails (`OSError: No such device or address: '/dev/tty'`). This skill bypasses that by walking the process tree to find the user's `claude` ancestor, reading its TTY from `/proc/<pid>/stat`, and writing Kitty graphics protocol escape sequences (`\x1b_G...\x1b\\`) directly to that PTY. Kitty intercepts the escapes at the terminal-emulator layer and renders the image into its image plane, on top of the text grid that the claude TUI is drawing. The image persists through claude's normal redraws because it lives on a separate render layer.

**Avoiding text overlap (important).** The image lives on Kitty's graphics layer, which Claude Code's renderer knows nothing about — so by default Claude packs its subsequent text right over the image's rows. Newlines written to the PTY don't help: Claude repaints from its own screen model and discards them. The fix is to reserve real vertical space in the one channel Claude *does* commit — the tool's **stdout**. `show.py` measures the image's row-height (PNG pixel height ÷ the PTY's per-cell pixel height from `TIOCGWINSZ`) and prints that many blank lines to stdout, so Claude reserves genuine rows that scroll and pack with the conversation. Two wrinkles are handled: the image anchors a few rows below the reserved block (it's drawn during the "Running" phase while stdout lays out afterward), so a `DRIFT_MARGIN` over-reserves to absorb the offset; and a trailing caption line (`└─ <filename>`) prevents the blank rows from being trimmed as trailing whitespace.

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
- **Images taller than the screen.** `image_rows()` caps reservation at `ws_row - 1`, so an image taller than the terminal can't be fully reserved and will overflow onto following text. For oversized images, fit-to-screen downscaling via the Kitty `r=` placement key would be needed (not yet implemented).
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

## Override and clear

```bash
# Force a specific PTY (if auto-detect fails or you want to target another tab)
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" /tmp/img.png --pts /dev/pts/4

# Clear all images currently on the active PTY
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" --clear
```

## Failure modes and what they mean

| Exit code | Meaning | Fix |
|-----------|---------|-----|
| 2 | Not running inside Kitty (`TERM != xterm-kitty`) | The skill cannot help; tell the user to open the file manually or use a Kitty-compatible terminal |
| 3 | No `claude` ancestor process found | The Bash environment is unusual; try `--pts` override |
| 4 | Detected PTY is not writable | Permission issue on `/dev/pts/<n>`; check ownership |
| 5 | Image file not found | Verify the path before calling the skill |
