#!/usr/bin/env python3
"""Display an image inline in the user's active Claude Code Kitty terminal.

The Claude Code Bash tool runs without a controlling TTY, so `kitty +kitten icat`
fails with "No such device or address: /dev/tty". This script bypasses that by:

  1. Walking the process tree to find the user's `claude` ancestor process.
  2. Reading that process's TTY from /proc/<pid>/stat (tty_nr field).
  3. Writing Kitty graphics protocol escape sequences directly to /dev/pts/<n>.

Kitty's terminal-emulator layer intercepts the escapes before the claude TUI
sees them, so the image renders into Kitty's image plane on top of the text grid.

Usage:
    python3 show.py <path_to_image>
    python3 show.py <path_to_image> --pts /dev/pts/N    (override auto-detect)
    python3 show.py --clear                              (delete all images)

Exit codes:
    0  success
    1  usage error
    2  not running inside Kitty (TERM != xterm-kitty)
    3  could not find claude ancestor process
    4  detected PTY is not writable
    5  image file not found / unreadable
    6  non-PNG input could not be converted (Pillow missing or unrecognized format)
"""
import argparse
import base64
import fcntl
import hashlib
import math
import os
import re
import struct
import sys
import termios
from pathlib import Path

# Kitty graphics protocol uses f=100 (PNG only). Non-PNG inputs are
# transcoded to PNG via Pillow in ensure_png_bytes().
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# ---------------------------------------------------------------------------
# Cell geometry
# ---------------------------------------------------------------------------
# Claude Code calls TIOCSWINSZ on its own PTY with ws_row/ws_col set and the
# pixel fields left as uninitialized garbage (observed: 49049 x 65238 on a
# window whose real cell is 10x22). Checking `ws_ypixel > 0` is therefore not
# enough -- the terminal doesn't stay silent, it lies. We check plausibility,
# and when our own PTY is untrustworthy we borrow the cell size from a sibling
# PTY of the same kitty: cell size is a property of the font, not the window.

DEFAULT_CELL = (10.0, 20.0)          # last resort; aspect 0.5 is mid-monospace
_CELL_W_RANGE = (3.0, 40.0)
_CELL_H_RANGE = (6.0, 80.0)
_CELL_ASPECT_RANGE = (0.25, 0.9)     # width/height of any real monospace glyph


def plausible_cell(cell_w: float, cell_h: float) -> bool:
    """True if (cell_w, cell_h) could plausibly be a real terminal cell."""
    if cell_w <= 0 or cell_h <= 0:
        return False
    if not _CELL_W_RANGE[0] <= cell_w <= _CELL_W_RANGE[1]:
        return False
    if not _CELL_H_RANGE[0] <= cell_h <= _CELL_H_RANGE[1]:
        return False
    return _CELL_ASPECT_RANGE[0] <= cell_w / cell_h <= _CELL_ASPECT_RANGE[1]


def cell_from_winsize(ws_row: int, ws_col: int,
                      ws_xpixel: int, ws_ypixel: int) -> tuple[float, float] | None:
    """Derive (cell_w, cell_h) from a winsize, or None if it isn't believable."""
    if ws_row <= 0 or ws_col <= 0 or ws_xpixel <= 0 or ws_ypixel <= 0:
        return None
    cell = (ws_xpixel / ws_col, ws_ypixel / ws_row)
    return cell if plausible_cell(*cell) else None


def resolve_cell(primary: dict | None,
                 siblings: list[dict]) -> tuple[float, float, str]:
    """Pick the best available cell geometry.

    Returns (cell_w, cell_h, source) where source is 'pty' | 'sibling' | 'default'.
    """
    if primary:
        cell = cell_from_winsize(**primary)
        if cell:
            return (*cell, "pty")
    for ws in siblings:
        cell = cell_from_winsize(**ws)
        if cell:
            return (*cell, "sibling")
    return (*DEFAULT_CELL, "default")


# ---------------------------------------------------------------------------
# Unicode placeholders
# ---------------------------------------------------------------------------
# A virtual placement (a=T,U=1) draws nothing by itself; kitty renders it only
# where U+10EEEE cells appear in the text stream. Those cells are ordinary text,
# so they land in Claude Code's committed transcript and scroll with it. The
# image id rides along as a 24-bit foreground colour; row/column ride as
# combining diacritics. Kitty auto-increments the column (and reuses the row)
# when the diacritics are omitted, so only each row's first cell needs them --
# without that, a full-screen grid blows past Claude's output cap.

PLACEHOLDER = "\U0010eeee"
_DIACRITICS_FILE = Path(__file__).with_name("rowcolumn-diacritics.txt")


def _load_diacritics(path: Path) -> list[int]:
    codes: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            codes.append(int(line.split(";")[0], 16))
    return codes


DIACRITICS = _load_diacritics(_DIACRITICS_FILE)
MAX_GRID = len(DIACRITICS)   # 297: the hard ceiling on addressable rows/columns


def image_id_for(png_bytes: bytes) -> int:
    """A stable, nonzero 24-bit id derived from the image bytes.

    24 bits because the id is carried in a truecolor SGR foreground. Content-
    derived so re-showing the same image reuses its slot, and two different
    images on screen at once never collide.
    """
    ident = int.from_bytes(hashlib.sha256(png_bytes).digest()[:3], "big") & 0xFFFFFF
    return ident or 1


def placeholder_grid(image_id: int, cols: int, rows: int) -> str:
    """Build the U+10EEEE cell block that makes a virtual placement visible."""
    if not 1 <= cols <= MAX_GRID or not 1 <= rows <= MAX_GRID:
        raise ValueError(
            f"grid {cols}x{rows} exceeds the {MAX_GRID} addressable rows/columns"
        )
    fg = "\x1b[38;2;{};{};{}m".format(
        (image_id >> 16) & 0xFF, (image_id >> 8) & 0xFF, image_id & 0xFF
    )
    col0 = chr(DIACRITICS[0])
    lines = []
    for row in range(rows):
        # First cell pins (row, col=0); the rest are bare and auto-increment.
        head = PLACEHOLDER + chr(DIACRITICS[row]) + col0
        lines.append(fg + head + PLACEHOLDER * (cols - 1) + "\x1b[0m")
    return "\n".join(lines)


def ensure_png_bytes(data: bytes, source_path: Path) -> bytes:
    """Return PNG bytes. Fast-path PNG; transcode anything else via Pillow.

    Raises RuntimeError if the input isn't PNG and Pillow can't read it
    (either Pillow is missing or the bytes are not a recognized image).
    """
    if data.startswith(PNG_MAGIC):
        return data
    try:
        import io
        from PIL import Image, UnidentifiedImageError
    except ImportError as e:
        raise RuntimeError(
            f"{source_path} is not PNG and Pillow is not installed; "
            "install python3-pil (apt) or pillow (pip) to enable conversion"
        ) from e
    try:
        with Image.open(io.BytesIO(data)) as img:
            # Modes that PNG can save losslessly. Anything else gets RGB-flattened.
            if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except UnidentifiedImageError as e:
        raise RuntimeError(
            f"{source_path} is not a recognizable image format"
        ) from e
    except Image.DecompressionBombError as e:
        # Pillow raises this for images whose pixel count is large enough to
        # look like a decompression bomb (default cap ~2x Image.MAX_IMAGE_PIXELS).
        # Fail cleanly instead of letting it surface as an uncaught traceback.
        raise RuntimeError(
            f"{source_path} exceeds the safe pixel limit (possible decompression bomb)"
        ) from e


def find_claude_pty() -> str:
    """Walk the process tree upward to find an ancestor named 'claude'
    and return its controlling PTY path (e.g. '/dev/pts/3').

    Raises RuntimeError if no claude ancestor is found.
    """
    pid = os.getpid()
    seen = set()
    while pid and pid != 1 and pid not in seen:
        seen.add(pid)
        try:
            with open(f"/proc/{pid}/stat", "r") as f:
                stat = f.read()
        except FileNotFoundError:
            break

        # /proc/<pid>/stat: "PID (comm) state PPID PGID SID TTY_NR ..."
        # comm can contain spaces/parens, so match the last ')' as the boundary.
        m = re.match(r"^\d+ \((.*)\) (\S) (\d+) \d+ \d+ (\d+)", stat)
        if not m:
            break
        comm = m.group(1)
        ppid = int(m.group(3))
        tty_nr = int(m.group(4))

        if comm.startswith("claude") and tty_nr != 0:
            # Decode tty_nr per Linux new_encode_dev: 12-bit major, split minor.
            # For pts, major is 136.
            major = (tty_nr >> 8) & 0xfff
            minor = (tty_nr & 0xff) | ((tty_nr >> 12) & 0xfff00)
            if major == 136:
                return f"/dev/pts/{minor}"
            # Fallback: read fd/0 of the claude process
            try:
                return os.readlink(f"/proc/{pid}/fd/0")
            except OSError:
                pass
        pid = ppid

    raise RuntimeError("no `claude` ancestor process found in the process tree")


def png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) in pixels from a PNG's IHDR chunk.

    Layout: 8-byte magic, 4-byte length, 4-byte "IHDR", then width and height
    as big-endian uint32 at offsets 16 and 20. Returns (0, 0) if unparseable.
    """
    if len(png_bytes) < 24 or png_bytes[12:16] != b"IHDR":
        return (0, 0)
    width, height = struct.unpack(">II", png_bytes[16:24])
    return (width, height)


def fit_cells(img_w: int, img_h: int, ws_row: int, ws_col: int,
              cell_w: float, cell_h: float, fit_height: bool = True) -> tuple[int, int]:
    """Pure sizing math: native image px + cell geometry -> (cols, rows).

    fit_height=True  (default): fit BOTH dims to the viewport.
    fit_height=False (--scroll): fit WIDTH only; never upscale; leave the height
        uncapped so the image scrolls. The terminal width is an upper bound, not
        a target — a capture narrower than the terminal keeps its native width.

    Both dimensions are capped at MAX_GRID, since a placeholder cell beyond the
    297th row/column has no diacritic to address it.
    Returns (1, 1) when geometry is unusable.
    """
    if img_w <= 0 or img_h <= 0 or cell_w <= 0 or cell_h <= 0:
        return (1, 1)
    nat_c = max(1, math.ceil(img_w / cell_w))
    nat_r = max(1, math.ceil(img_h / cell_h))
    avail_c = max(1, (ws_col - 1) if ws_col > 0 else nat_c)
    avail_c = min(avail_c, MAX_GRID)

    if not fit_height:
        # Fit width only. Never enlarge; height uncapped (scrolls) up to MAX_GRID.
        scale = min(1.0, avail_c / nat_c, MAX_GRID / nat_r)
        if scale >= 1.0:
            return (nat_c, nat_r)
        return (max(1, min(avail_c, round(nat_c * scale))),
                max(1, min(MAX_GRID, round(nat_r * scale))))

    avail_r = max(1, min(ws_row - 2 if ws_row > 0 else nat_r, MAX_GRID))
    if nat_c <= avail_c and nat_r <= avail_r:
        return (nat_c, nat_r)
    scale = min(avail_c / nat_c, avail_r / nat_r)
    fit_c = max(1, min(avail_c, round(nat_c * scale)))
    fit_r = max(1, min(avail_r, round(nat_r * scale)))
    return (fit_c, fit_r)


def read_winsize(fd: int) -> dict:
    """TIOCGWINSZ -> {ws_row, ws_col, ws_xpixel, ws_ypixel}."""
    packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\x00" * 8)
    ws_row, ws_col, ws_xpixel, ws_ypixel = struct.unpack("HHHH", packed)
    return dict(ws_row=ws_row, ws_col=ws_col,
                ws_xpixel=ws_xpixel, ws_ypixel=ws_ypixel)


def sibling_winsizes(exclude: str) -> list[dict]:
    """Winsizes of every other PTY we can open, for cell-geometry fallback.

    O_NOCTTY is mandatory: opening a PTY slave without it would make that PTY
    our controlling terminal if we happen to be a session leader without one.
    O_NONBLOCK avoids blocking on a PTY with no writer.
    """
    out: list[dict] = []
    try:
        entries = sorted(e for e in os.listdir("/dev/pts") if e.isdigit())
    except OSError:
        return out
    for entry in entries:
        path = f"/dev/pts/{entry}"
        if path == exclude:
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            out.append(read_winsize(fd))
        except OSError:
            pass
        finally:
            os.close(fd)
    return out


def placement_cells(tty_fd: int, pts_path: str, png_bytes: bytes,
                    fit_height: bool = True) -> tuple[int, int, str]:
    """Return (cols, rows, cell_source) for the image."""
    img_w, img_h = png_dimensions(png_bytes)
    try:
        primary = read_winsize(tty_fd)
    except OSError:
        primary = None
    cell_w, cell_h, source = resolve_cell(primary, sibling_winsizes(pts_path))
    ws_row = primary["ws_row"] if primary else 0
    ws_col = primary["ws_col"] if primary else 0
    cols, rows = fit_cells(img_w, img_h, ws_row, ws_col, cell_w, cell_h, fit_height)
    return cols, rows, source


def send_kitty_graphics(png_bytes: bytes, pts_path: str,
                        fit_height: bool = True) -> tuple[int, int, int, str]:
    """Transmit the image and create a VIRTUAL placement (U=1).

    Returns (chunk_count, cols, rows, cell_source).

    A virtual placement draws nothing on its own — it only appears where the
    caller prints U+10EEEE placeholder cells (see placeholder_grid). That is the
    entire point: direct-paint (a=T without U=1) anchors the image at the PTY
    cursor, which during Claude Code's "Running" phase sits at the bottom of the
    screen, so the image ends up pinned below the prompt and clipped. Placeholder
    cells are ordinary text in Claude's committed stdout, so the image lands in
    the transcript and scrolls with it.

    q=2 suppresses kitty's OK response, which would otherwise be written into
    claude's stdin.
    """
    b64 = base64.standard_b64encode(png_bytes).decode("ascii")
    chunk_size = 4096
    chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
    image_id = image_id_for(png_bytes)
    with open(pts_path, "w") as tty:
        cols, rows, source = placement_cells(tty.fileno(), pts_path, png_bytes, fit_height)
        for i, chunk in enumerate(chunks):
            more = 1 if i < len(chunks) - 1 else 0
            if i == 0:
                tty.write(f"\x1b_Ga=T,U=1,i={image_id},f=100,"
                          f"c={cols},r={rows},q=2,m={more};{chunk}\x1b\\")
            else:
                tty.write(f"\x1b_Gm={more};{chunk}\x1b\\")
        tty.flush()
    return len(chunks), cols, rows, source


def clear_images(pts_path: str) -> None:
    """Delete all placements AND the stored image data.

    d=A is required: a bare `a=d` deletes only *visible* placements, leaving
    virtual placements and the images themselves resident in kitty's memory.
    """
    with open(pts_path, "w") as tty:
        tty.write("\x1b_Ga=d,d=A,q=2\x1b\\")
        tty.flush()


def detect_pts(override: str | None) -> str:
    if override:
        return override
    return find_claude_pty()


def main() -> int:
    ap = argparse.ArgumentParser(description="Render image in Claude Code Kitty terminal.")
    ap.add_argument("image", nargs="?", help="path to PNG/JPEG image")
    ap.add_argument("--pts", help="override auto-detected PTY (e.g. /dev/pts/4)")
    ap.add_argument("--clear", action="store_true", help="delete all images on the terminal")
    ap.add_argument("--scroll", action="store_true",
                    help="fit to width only and leave the height uncapped so a tall "
                         "image scrolls (instead of being shrunk to fit the screen)")
    args = ap.parse_args()

    if not args.clear and not args.image:
        ap.error("image path required (or pass --clear)")

    if os.environ.get("TERM", "") != "xterm-kitty":
        # Not fatal if user explicitly overrides --pts — they may know better.
        if not args.pts:
            print("error: TERM is not xterm-kitty; this skill only works in Kitty.",
                  file=sys.stderr)
            return 2

    try:
        pts = detect_pts(args.pts)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    if not os.access(pts, os.W_OK):
        print(f"error: {pts} is not writable", file=sys.stderr)
        return 4

    if args.clear:
        clear_images(pts)
        print(f"cleared images on {pts}")
        return 0

    p = Path(args.image)
    if not p.is_file():
        print(f"error: {p} not found", file=sys.stderr)
        return 5

    data = p.read_bytes()
    try:
        png_data = ensure_png_bytes(data, p)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 6
    n, cols, rows, cell_source = send_kitty_graphics(png_data, pts,
                                                     fit_height=not args.scroll)
    converted = "" if png_data is data else " (converted to PNG)"
    # The placeholder grid IS the image, as far as Claude's renderer is concerned:
    # ordinary text cells in the committed tool-result block. No blank-line
    # reservation and no drift margin are needed, because the image is anchored by
    # these cells rather than by wherever the PTY cursor happened to be.
    #
    # Strip non-printable characters from the filename before echoing it, so a
    # name containing terminal control/escape bytes can't smuggle anything into
    # the output. (Defense-in-depth: this goes to stdout, not the raw PTY.)
    safe_name = "".join(c for c in p.name if c.isprintable()) or "image"
    sys.stdout.write(placeholder_grid(image_id_for(png_data), cols, rows) + "\n")
    sys.stdout.write(f"└─ {safe_name}\n")
    print(f"[kitty-image] sent {len(png_data)} bytes ({n} chunks) as a "
          f"{cols}x{rows} cell placement to {pts} "
          f"[cell geometry: {cell_source}]{converted}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
