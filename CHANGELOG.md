# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-07-09
### Changed
- **Images are now drawn with Unicode placeholders instead of direct paint.** `show.py` creates a virtual placement (`a=T,U=1,i=<id>`) and prints a grid of `U+10EEEE` cells to stdout; Kitty substitutes the image where those cells land. Because the cells are ordinary text in Claude Code's committed tool output, the image renders inline and scrolls with the conversation. The old `a=T` direct paint anchored the image at the PTY cursor — during Claude's "Running" phase that is the bottom of the screen — so images appeared pinned below the prompt, clipped at the screen edge, and never scrolled.
- **Cell geometry is validated rather than trusted.** Claude Code sets its PTY's winsize with the pixel fields left as uninitialized garbage (observed `49049 x 65238` where the real cell is `10 x 22`), which the old `ws_ypixel > 0` guard happily accepted — collapsing a 900x408 image to a 4x1 cell box. `plausible_cell()` now range-checks the derived cell and `resolve_cell()` falls back to a sibling PTY's geometry (same font ⇒ same cell) before a built-in default. The source is reported on stderr.
- `--clear` now sends `a=d,d=A`, deleting placements *and* stored image data. A bare `a=d` left virtual placements and image data resident in Kitty's memory.
- `fit_cells()` takes a resolved cell size rather than raw winsize pixels, and caps both dimensions at 297 cells (Kitty's addressable placeholder grid).

### Removed
- `DRIFT_MARGIN` and the blank-line stdout reservation. Placeholder cells anchor the image exactly, so there is no anchor/stdout offset left to absorb.

### Requirements
- **Kitty >= 0.28** (>= 0.29.1 recommended). Unicode placeholders do not exist before 0.28 and render as literal garbage glyphs there.

### Notes
- Callers must not capture or discard `show.py`'s stdout — the placeholder grid *is* the image. `mermaid.py` and `html.py` inherit stdout and are unaffected.

## [0.4.0] - 2026-05-30
### Added
- **HTML → inline image** (`html.py`): render a live URL, a local HTML file, or stdin HTML to a PNG and display it inline. Drives Puppeteer-core against the system Chrome (installed once into a user cache; no Chromium download), then hands off to `show.py`. Capture modes: viewport (default), `--selector` (one element), `--full-page`.
- `show.py --scroll`: fit-to-width display with uncapped, scrollable height — never upscales. Used for full-page captures so long pages stay readable instead of being shrunk to fit.

### Changed
- Extracted shared browser/PNG/display helpers into `_chrome.py`, used by both `mermaid.py` and `html.py` (no behavior change to mermaid rendering).
- `show.py`'s sizing math is now a pure `fit_cells()` function (unit-tested); default fit-to-screen behavior is unchanged.

## [0.3.0] - 2026-05-30
### Added
- **Fit-to-screen scaling** (`placement_cells()`): images larger than the terminal are downscaled to fit, preserving aspect ratio, by passing a `(cols, rows)` box to Kitty via the `c=`/`r=` placement keys. Images that already fit are rendered pixel-for-pixel as before. This also applies to Mermaid diagrams, since `mermaid.py` displays through `show.py`.

### Changed
- `image_rows()` (reserve-only, height capped at `ws_row - 1`, which let oversized images overflow onto following text) is replaced by `placement_cells()`, which returns a concrete fit-to-screen cell box. The vertical fit reserves `DRIFT_MARGIN + 2` rows of headroom so a downscaled image plus its anchor offset stay on one screen.
- Dropped the leading PTY newline in the placement path: with cursor policy `C=1` and the stdout row reservation, it only added an uncommitted top gap that Claude's renderer doesn't account for.

## [0.2.0] - 2026-05-29
### Added
- **Mermaid diagram rendering** (`mermaid.py`): turn a Mermaid definition (flowchart, sequence, state, ER, class, architecture) into an inline PNG. Renders the diagram and hands off to `show.py` for display in one step; reads from a `.mmd` file or stdin (`-`).
- Local-first rendering for privacy: uses `mmdc` if present, else `npx -p @mermaid-js/mermaid-cli mmdc` pointed at an already-installed Chrome (no Puppeteer Chromium download). The diagram text never leaves the machine unless `--remote` is passed, which renders via the public mermaid.ink service.
- Defaults (`--theme dark`, `--bg '#10121a'`, `--scale 2`) match the existing Pillow chart aesthetic. Dedicated exit codes 10–13 for renderer-missing, render-failure, remote-failure, and bad-input.

### Changed
- Relicensed from PolyForm Noncommercial 1.0.0 to MIT — free to use, modify, and distribute, including commercially.
- Documented `show.py` exit code 6 (non-PNG conversion failure) in the SKILL.md failure-modes table.

## [0.1.2] - 2026-05-23
### Changed
- Reframed the skill from a chart/data-viz tool to general inline image display.
- Documented the obtain-then-show path (search for a real image URL, download, display) and clarified that it respects the "don't fabricate URLs" rule. Requests like "show me a picture of a puppy" now render an image instead of being refused or described in prose.

## [0.1.1] - 2026-05-23
### Security
- Strip non-printable characters from the filename before echoing it, so a name containing terminal control/escape bytes cannot be smuggled into output.
- Catch Pillow's `DecompressionBombError` in the non-PNG path and fail cleanly instead of raising an uncaught traceback.

## [0.1.0] - 2026-05-23
### Added
- Initial release: display PNG/JPEG images inline in a Claude Code session running in the Kitty terminal, working around the Bash tool's lack of a controlling TTY.
- stdout-based row reservation so Claude's following text does not overlap the rendered image.

[Unreleased]: https://github.com/whallil/claude-kitty-image/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/whallil/claude-kitty-image/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/whallil/claude-kitty-image/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/whallil/claude-kitty-image/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/whallil/claude-kitty-image/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/whallil/claude-kitty-image/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/whallil/claude-kitty-image/releases/tag/v0.1.0
