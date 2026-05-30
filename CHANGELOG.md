# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
