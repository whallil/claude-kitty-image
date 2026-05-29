# Design: Mermaid workflow diagrams for kitty-image

**Date:** 2026-05-29
**Status:** Approved (design); implementation in progress
**Branch:** worktree-mermaid-diagrams

## Problem

The `kitty-image` skill displays an existing PNG/JPEG inline in a Kitty terminal. To
show a *workflow* today, the caller must hand-produce a raster image (Pillow boxes and
arrows by hand, or matplotlib). There is no first-class way to go from a **mermaid**
diagram definition (`graph TD; A-->B`) to an inline image, even though mermaid is the
natural language for flowcharts, sequence, state, and workflow diagrams.

## Goal

Let Claude (proactively) and the user turn a mermaid diagram definition into an inline
terminal image, reusing the existing display path, while staying:

- **Portable** — the plugin ships to all installers; must degrade gracefully where
  no renderer exists.
- **Privacy-first** — default to local rendering; never send diagram text off-box
  unless the user explicitly opts in.
- **Dependency-honest** — like the existing skill (Pillow "always available",
  matplotlib optional), be explicit that mermaid needs node+Chrome locally, or `--remote`.

## Non-goals

- Editing/round-tripping mermaid. We render a definition to a PNG, full stop.
- Supplanting the Pillow/matplotlib chart pattern — that stays for data charts.
- Inline display from a background job (the existing PTY-detection limitation is
  unchanged; render works anywhere, display needs the live `claude` TUI).

## Empirically verified on this box (2026-05-29)

Both render paths were tested for real before writing this spec, and the live tests
**overruled the docs in two places** (see "Research vs reality" below):

- **Local (default):**
  `PUPPETEER_SKIP_DOWNLOAD=1 npx --yes -p @mermaid-js/mermaid-cli mmdc -i in.mmd -o out.png -t dark -b '#10121a' -s 2 -p puppeteer.json`
  where `puppeteer.json` = `{"executablePath":"/bin/google-chrome","args":["--no-sandbox","--disable-gpu"]}`
  → exit 0, **746×1100 dark RGB PNG**, ~17s first run (incl. package download),
  **~1.65s cached**, reuses system `google-chrome` (no Chromium download).
  `executablePath` lives **in the config file** (officially documented, version-robust);
  the env var `PUPPETEER_EXECUTABLE_PATH` *also* works but the config is primary.
- **Remote (`--remote` opt-in):** **pako envelope** —
  `python3` builds `pako:` + base64url(zlib.deflate(JSON `{"code":<diagram>,"mermaid":{"theme":"dark"}}`)),
  then `curl 'https://mermaid.ink/img/pako:<...>?type=png&bgColor=10121a'`
  → HTTP 200, `image/png`, dark-themed **RGB** PNG (theme + solid bg applied).
  Plain base64url *also* still works today but yields a light, transparent (RGBA)
  image and is not URL-safe for diagrams whose base64 contains `/`.

### Research vs reality (resolved by live test)

| Doc claim (research) | Live result | Decision |
|----------------------|-------------|----------|
| mermaid.ink: plain base64 dead, returns "invalid encoded code" | Plain base64url still returns a valid PNG | Use **pako** anyway — URL-safe, compressed (no 414), carries dark theme/bg |
| mmdc: `PUPPETEER_EXECUTABLE_PATH` "does NOT work" | It *did* reuse google-chrome | Put `executablePath` **in config** (robust) + keep env var as backup |

## Architecture

```
diagram.mmd ──> mermaid.py ──(renders PNG to /tmp)──> show.py ──> Kitty inline
                    │
                    ├─ backend resolution (local-first):
                    │    1. mmdc on PATH
                    │    2. else npx + detected Chrome
                    │    3. else FAIL(10) suggesting --remote
                    └─ --remote: base64 → curl mermaid.ink → PNG
```

`mermaid.py` is **render-only**; display stays in `show.py`. They communicate through a
PNG file path — the same contract `show.py` already has with every other caller.

## Component: `mermaid.py`

Lives at `plugins/kitty-image/skills/kitty-image/mermaid.py`.

### Interface

```
python3 mermaid.py <diagram.mmd>          # render → /tmp PNG → exec show.py
python3 mermaid.py -                       # read diagram from stdin
python3 mermaid.py <file> --remote         # explicit opt-in: hosted renderer
python3 mermaid.py <file> --theme dark     # mermaid theme (default: dark)
python3 mermaid.py <file> --bg '#10121a'   # background (default: skill bg)
python3 mermaid.py <file> --scale 2        # render scale (default: 2)
python3 mermaid.py <file> --out PATH       # output PNG path (default: /tmp/<name>.png)
python3 mermaid.py <file> --no-show        # render only, print path, skip display
python3 mermaid.py <file> --pts /dev/pts/N # passthrough to show.py
```

Primary input is a **file path** (Claude writes the `.mmd` with the Write tool — avoids
fragile shell-escaping of multi-line diagrams). `-` reads stdin as a convenience.

### Backend resolution (local-first; privacy default)

1. **`mmdc` on `PATH`** → use it directly (fastest, fully offline, private).
2. **else `npx` present AND a Chrome binary detected** (search order:
   `google-chrome`, `google-chrome-stable`, `chromium`, `chromium-browser`, `chrome`)
   → `npx --yes -p @mermaid-js/mermaid-cli mmdc ...` with `PUPPETEER_SKIP_DOWNLOAD=1`
   and a temp `puppeteer.json` carrying `{"executablePath":<chrome>,"args":["--no-sandbox","--disable-gpu"]}`.
   `PUPPETEER_EXECUTABLE_PATH=<chrome>` is also exported as a backup.
3. **else** → exit **10** with a clear message:
   *"No local mermaid renderer (need `mmdc`, or `node`+Chrome). Re-run with `--remote`
   to use mermaid.ink — note this sends the diagram text to a third-party service."*

`--remote` **skips 1–2 entirely** and does the hosted path: build the **pako envelope**
(`pako:` + base64url(zlib.deflate(JSON `{"code":<diagram>,"mermaid":{"theme":<theme>}}`))),
`curl 'https://mermaid.ink/img/pako:<...>?type=png&bgColor=<hex-no-#>'`, save PNG.
Nothing leaves the box unless `--remote` is passed.

> **Why local-first, hosted opt-in:** the diagram text is the payload, and workflow
> diagrams can encode internal architecture. Defaulting to local keeps that on-box;
> `--remote` is a deliberate, logged choice.

### Theming

Defaults match the skill's chart aesthetic so diagrams look consistent with Pillow
charts: `--theme dark`, `--bg '#10121a'` (the skill's `(16,18,26)`), `--scale 2`
(crisp text). All overridable. For `--remote`, theme/bg are mapped to mermaid.ink's
query params where supported; otherwise the service default is used (documented).

### Display handoff

On successful render, `mermaid.py` invokes `show.py <png>` (via `subprocess`,
forwarding `--pts` if given) so reservation / anti-overlap / caption logic is reused
unchanged. `--no-show` prints the path and exits (useful for bg jobs / piping).

## Error handling — new exit codes

Distinct from `show.py`'s existing 2–5 so failures are unambiguous when chained:

| Code | Meaning | Surfaced fix |
|------|---------|--------------|
| 10 | No local renderer found and `--remote` not given | message suggests `--remote` |
| 11 | Local render (mmdc/npx) failed — e.g. bad mermaid syntax | mermaid's stderr is forwarded |
| 12 | `--remote` failed — network / service / non-PNG response | show HTTP status + body head |
| 13 | Input diagram file not found / empty | verify path |

`show.py`'s own codes (2 not-Kitty, 3 no-claude-ancestor, 4 PTY-not-writable,
5 image-not-found) still propagate when the display step runs.

## SKILL.md updates

- **Frontmatter `description`:** add mermaid/workflow-diagram triggering so the skill
  fires when a user wants to *see a workflow/flowchart/sequence/state diagram*.
- **"When to invoke":** add a bullet for rendering a mermaid definition.
- **New section "Mermaid workflow diagrams":** the write-`.mmd`→`mermaid.py` flow, the
  local-first/`--remote` privacy stance, the dependency reality (node+Chrome or
  `--remote`), and the default dark theming.
- **Failure-modes table:** add codes 10–13.

## Testing

1. **Local happy path** — render `sample.mmd` via npx+google-chrome, assert exit 0 and
   a valid PNG of expected dimensions. (✓ already verified manually.)
2. **Remote happy path** — `--remote` against mermaid.ink, assert PNG. (✓ verified.)
3. **Bad syntax** — malformed diagram → exit 11 with mermaid's error surfaced.
4. **No renderer** — invoke with `PATH` stripped of node/mmdc and no `--remote`
   → exit 10 with the `--remote` hint.
5. **Missing input** — nonexistent `.mmd` → exit 13.
6. **stdin** — `cat sample.mmd | mermaid.py - --no-show` → prints a valid PNG path.
7. **Display chain** — `--no-show` omitted in a live Kitty TUI displays inline (manual,
   cannot be exercised from a background job).

## Open questions resolved during research + live test

- mermaid.ink encoding: **pako envelope** chosen (verified working, applies dark theme +
  solid bg, URL-safe, compressed). Plain base64url also works today but is light/RGBA and
  not URL-safe for all diagrams.
- Reusing system Chrome under npx: **`executablePath` in the puppeteer config file**
  (verified) avoids the ~150–200 MB Chromium download; `PUPPETEER_SKIP_DOWNLOAD=1` keeps
  npx from fetching one during install. ~1.65s per render once cached.
- kroki.io retained as a *documented* alternative remote backend, not implemented in v1
  (kroki PNG is always transparent with no solid-bg option, so it can't match the dark
  aesthetic, and its GET needs raw zlib + base64url). Revisit only if mermaid.ink is down.
