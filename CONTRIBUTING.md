# Contributing to kitty-image

Thanks for your interest in improving kitty-image! This is a small, focused project, so contributions of any size are welcome — bug reports, doc fixes, or code.

## Project layout

```
.claude-plugin/marketplace.json       # makes the repo an installable marketplace
plugins/kitty-image/
  .claude-plugin/plugin.json           # plugin manifest
  skills/kitty-image/
    SKILL.md                           # how/when Claude uses the skill
    show.py                            # the actual renderer (stdlib only)
```

`show.py` is the whole engine. It is intentionally **standard-library only** so it runs anywhere Python 3 does. The single optional dependency is [Pillow](https://python-pillow.org/), used *only* to transcode non-PNG input to PNG. Please keep it that way — new hard dependencies will be declined.

## Development setup

You need the Kitty terminal and Python 3. Clone the repo and run the script directly:

```bash
python3 plugins/kitty-image/skills/kitty-image/show.py /path/to/image.png
```

To exercise it as an installed plugin in Claude Code, point a marketplace at your local clone:

```
/plugin marketplace add /absolute/path/to/your/clone
/plugin install kitty-image@thistle-intelligence
```

## Before you open a PR

- Run `python3 -m py_compile plugins/kitty-image/skills/kitty-image/show.py` (CI runs this too).
- If you changed rendering or layout behavior, **test it in a real Kitty terminal**. Screenshots in the PR are very welcome — the whole point of this tool is visual.
- Keep `show.py` dependency-light and readable. Comments should explain *why*, not *what*.
- Add an entry to `CHANGELOG.md` under the "Unreleased" heading.

## Reporting bugs / requesting features

Use the issue templates. For anything security-sensitive, follow [SECURITY.md](SECURITY.md) — please don't open a public issue for vulnerabilities.

## License

By contributing, you agree that your contributions are licensed under the project's [PolyForm Noncommercial 1.0.0](LICENSE) license.
