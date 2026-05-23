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


def image_rows(tty_fd: int, png_bytes: bytes) -> int:
    """How many text rows the image occupies, so we can reserve that space.

    Queries the PTY geometry (TIOCGWINSZ gives total rows + pixel size, hence
    the per-cell pixel height) and divides the PNG's pixel height by it. Rounds
    up so we never under-reserve (a sub-cell gap is harmless; overlap is the bug
    we're fixing). Capped to one less than the screen height. Returns 1 if the
    geometry can't be determined (e.g. terminal reports 0 pixels).
    """
    _, img_h = png_dimensions(png_bytes)
    if img_h <= 0:
        return 1
    try:
        packed = fcntl.ioctl(tty_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        ws_row, _ws_col, _ws_xpixel, ws_ypixel = struct.unpack("HHHH", packed)
    except OSError:
        return 1
    if ws_row <= 0 or ws_ypixel <= 0:
        return 1
    cell_h = ws_ypixel / ws_row
    rows = math.ceil(img_h / cell_h)
    return max(1, min(rows, ws_row - 1))


def send_kitty_graphics(png_bytes: bytes, pts_path: str) -> tuple[int, int]:
    """Write Kitty graphics protocol escapes to pts_path.

    Returns (chunk_count, image_rows). We set cursor policy C=1 so the image
    placement does not move the cursor; the caller reserves vertical space via
    stdout (see main) rather than via PTY newlines, because directly-injected
    newlines don't survive Claude Code's independent screen repaint.
    """
    b64 = base64.standard_b64encode(png_bytes).decode("ascii")
    chunk_size = 4096
    chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
    with open(pts_path, "w") as tty:
        rows = image_rows(tty.fileno(), png_bytes)
        tty.write("\n")  # leading newline so image doesn't collide with cursor row
        for i, chunk in enumerate(chunks):
            more = 1 if i < len(chunks) - 1 else 0
            if i == 0:
                tty.write(f"\x1b_Gf=100,a=T,C=1,m={more};{chunk}\x1b\\")
            else:
                tty.write(f"\x1b_Gm={more};{chunk}\x1b\\")
        tty.flush()
    return len(chunks), rows


def clear_images(pts_path: str) -> None:
    """Send 'delete all images' escape sequence."""
    with open(pts_path, "w") as tty:
        tty.write("\x1b_Ga=d\x1b\\")
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
    n, rows = send_kitty_graphics(png_data, pts)
    converted = "" if png_data is data else " (converted to PNG)"
    # Reserve the image's height as REAL rows in Claude's committed tool-result
    # block. stdout is the only channel Claude's renderer accounts for, so blank
    # lines here scroll and pack correctly with the rest of the conversation;
    # newlines written to the PTY do not.
    #
    # The image is drawn to the PTY during the "Running" phase, so it anchors a
    # few rows BELOW the top of this stdout block (the gap is ~the height of the
    # command-echo header). DRIFT_MARGIN over-reserves to absorb that offset so
    # the image floats inside the blank block instead of spilling onto the text
    # that follows. The trailing marker keeps the rows from being trimmed.
    DRIFT_MARGIN = 6
    reserved = rows + DRIFT_MARGIN
    # Strip non-printable characters from the filename before echoing it, so a
    # name containing terminal control/escape bytes can't smuggle anything into
    # the output. (Defense-in-depth: this goes to stdout, not the raw PTY.)
    safe_name = "".join(c for c in p.name if c.isprintable()) or "image"
    sys.stdout.write("\n" * (reserved - 1))
    sys.stdout.write(f"└─ {safe_name}\n")  # caption + trim guard for the blank rows
    print(f"[kitty-image] sent {len(png_data)} bytes ({n} chunks, "
          f"{reserved} rows reserved for {rows}-row image) to {pts}{converted}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
