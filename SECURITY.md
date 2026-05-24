# Security Policy

## Supported versions

This project is pre-1.0 and ships fixes only on the latest released version. Always run the most recent `0.1.x`.

| Version       | Supported |
|---------------|-----------|
| latest 0.1.x  | ✅        |
| anything older| ❌        |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

This repo has GitHub private vulnerability reporting enabled. Go to the **Security** tab → **Report a vulnerability**, or use this link:

https://github.com/whallil/claude-kitty-image/security/advisories/new

That opens a private channel between you and the maintainer. Please include reproduction steps, the affected version, and the impact you can demonstrate. This is a hobby-scale project, so expect an initial response within a few days — thanks for your patience.

## What this tool actually does (scope for reviewers)

`show.py` is deliberately small and easy to audit:

- **No network access.** It never makes outbound connections. (Claude may *separately* fetch an image to display, but that is Claude's action, not this script's.)
- **No shell, no `eval`, no subprocess.** There is no command-injection surface.
- **Writes only to your own terminal.** It locates the `claude` process's PTY via `/proc` and writes Kitty graphics escapes there. The `--pts` override is gated by `os.access(..., W_OK)`, so it cannot write to a terminal you don't already own — no privilege escalation.
- **Image bytes are base64-encoded before they reach the terminal**, so a malicious image file cannot inject terminal escape sequences.
- **Optional Pillow** is used only to transcode non-PNG input; PNG input never touches an image parser, and the decompression-bomb case is caught explicitly.

The most realistic risk surface is Pillow's decoding of non-PNG inputs. Reports there are welcome, but may be better directed upstream to Pillow.
