# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/whallil/claude-kitty-image/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/whallil/claude-kitty-image/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/whallil/claude-kitty-image/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/whallil/claude-kitty-image/releases/tag/v0.1.0
