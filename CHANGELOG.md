# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/whallil/claude-kitty-image/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/whallil/claude-kitty-image/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/whallil/claude-kitty-image/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/whallil/claude-kitty-image/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/whallil/claude-kitty-image/releases/tag/v0.1.0
