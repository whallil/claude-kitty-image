# claude-kitty-image

[![validate](https://github.com/whallil/claude-kitty-image/actions/workflows/validate.yml/badge.svg)](https://github.com/whallil/claude-kitty-image/actions/workflows/validate.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Show real PNG/JPEG images **inline** in a [Claude Code](https://claude.com/claude-code) session running inside the [Kitty](https://sw.kovidgoyal.net/kitty/) terminal — charts, diagrams, screenshots, rendered output — without them overlapping the text Claude prints afterward.

![Claude Code rendering a generated image inline in the Kitty terminal via kitty-image](assets/demo.png)

It ships as a Claude Code **plugin** containing a single skill, `kitty-image`, that Claude invokes automatically whenever you ask for a chart, plot, diagram, or any visual that block-character ASCII can't do justice. It also renders **[Mermaid](https://mermaid.js.org) diagrams** — flowcharts, sequence and state diagrams, workflows — straight to an inline image (see [Mermaid diagrams](#mermaid-diagrams)).

## The problem it solves

Claude Code's Bash tool runs with no controlling TTY, so the normal `kitty +kitten icat` fails:

```
OSError: No such device or address: '/dev/tty'
```

This plugin walks the process tree to find your `claude` process, reads its real PTY, and writes [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/) escape sequences straight to it. Kitty renders the image on its own graphics layer.

The harder problem is **layout**: that graphics layer is invisible to Claude's text renderer, so by default Claude packs its next message right on top of the image. This plugin fixes that by measuring the image's height in terminal rows (from the PNG header + the PTY's pixel geometry) and reserving that many real rows through the tool's stdout — the one channel Claude commits to its screen model — so following text lands cleanly below the image.

## Requirements

- **Kitty terminal** (`TERM=xterm-kitty`). The skill refuses to run elsewhere. Other Kitty-protocol terminals (Ghostty, WezTerm, Konsole, iTerm2) may work with a manual `--pts` override, but are untested.
- **Python 3** (standard library only). [Pillow](https://python-pillow.org/) is optional — needed only to transcode non-PNG input (e.g. JPEG) to PNG.
- Linux. PTY discovery reads `/proc`, so macOS is not currently supported.
- **Mermaid rendering (optional).** For local rendering you need either [`mermaid-cli`](https://github.com/mermaid-js/mermaid-cli) (`mmdc`) on `PATH`, or `npx` (Node) plus an installed Chrome/Chromium. No local renderer? Pass `--remote` to render via the public [mermaid.ink](https://mermaid.ink) service instead — that sends the diagram text off-box, so it's opt-in only.

## Install

In Claude Code:

```
/plugin marketplace add whallil/claude-kitty-image
/plugin install kitty-image@thistle-intelligence
```

That's it. Ask Claude for a chart or diagram and it will render inline.

## Usage

Normally you don't call anything — Claude invokes the skill on its own. To drive the script directly:

```bash
# Display an image
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" /path/to/image.png

# Target a specific PTY if auto-detect picks the wrong one
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" /path/to/image.png --pts /dev/pts/4

# Clear all images on the active PTY
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/show.py" --clear
```

### Mermaid diagrams

Write a Mermaid definition to a `.mmd` file and render it inline in one step (`mermaid.py` renders the PNG, then hands off to `show.py`):

```bash
cat > /tmp/flow.mmd <<'EOF'
graph TD
    A[Start] --> B{Renderer available?}
    B -->|local mmdc| C[Render offline]
    B -->|--remote| D[mermaid.ink]
    C --> E[Display inline]
    D --> E
EOF

# Local render (default): dark theme, #10121a background, 2x scale
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/mermaid.py" /tmp/flow.mmd

# No local renderer? Opt in to the hosted mermaid.ink service
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kitty-image/mermaid.py" /tmp/flow.mmd --remote
```

Rendering is **local-first**: the diagram text never leaves your machine unless you pass `--remote`. Flags: `--theme`, `--bg`, `--scale`, `--out`, `--no-show`, `--pts`.

## Known limitations

- **Drift margin is a heuristic.** Space reservation adds a small fixed margin to absorb the offset between where the image anchors and where the reserved rows land. For the skill's normal one-line invocation this is stable; a pathologically long, wrapping command could still clip a row or two.
- **Images larger than the screen** are automatically scaled down to fit (aspect preserved) using Kitty's `c=`/`r=` placement keys, so they no longer overflow off the bottom. Images that already fit are shown at native size. Auto-fit needs the terminal to report pixel geometry (Kitty does); otherwise it falls back to native size.
- **Persistence.** Images stay until Kitty scrolls them out of view, you clear the screen, or you run `--clear`. Claude's redraws don't remove them.

## License

[MIT](./LICENSE) © Thistle Intelligence, LLC. Free to use, modify, and distribute, including commercially.
