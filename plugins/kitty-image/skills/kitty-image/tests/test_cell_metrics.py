"""Cell-geometry resolution: trust the PTY only when it reports plausible pixels.

Claude Code calls TIOCSWINSZ on its own PTY with ws_row/ws_col populated and the
pixel fields left as uninitialized garbage (observed: 49049 x 65238 on a terminal
whose real cell is 10x22). The old `ws_ypixel <= 0` guard only caught *zero*, so
the garbage flowed into the sizing math and collapsed a 900x408 image to a 4x1
cell box. These tests pin the plausibility check and the sibling-PTY fallback.
"""
import show

# Real values observed on a kitty 0.47.4 window: 192x42 cells, 1920x924 px.
SANE = dict(ws_row=42, ws_col=192, ws_xpixel=1920, ws_ypixel=924)   # cell 10.0 x 22.0
# Real garbage observed on claude's own PTY in that same window.
GARBAGE = dict(ws_row=42, ws_col=192, ws_xpixel=49049, ws_ypixel=65238)


class TestPlausibleCell:
    def test_accepts_typical_monospace_cells(self):
        assert show.plausible_cell(10.0, 22.0)   # this machine
        assert show.plausible_cell(6.0, 13.0)    # small font
        assert show.plausible_cell(20.0, 40.0)   # hidpi / large font

    def test_rejects_the_observed_garbage(self):
        # cell 255.5 x 1553.3, aspect 0.164
        assert not show.plausible_cell(255.5, 1553.3)

    def test_rejects_zero_and_negative(self):
        assert not show.plausible_cell(0, 0)
        assert not show.plausible_cell(10.0, 0)
        assert not show.plausible_cell(-10.0, 22.0)

    def test_rejects_implausible_aspect_even_at_sane_heights(self):
        # A 22px-tall cell that is 2px wide is not a real font.
        assert not show.plausible_cell(2.0, 22.0)
        # ...nor one that is wider than it is tall.
        assert not show.plausible_cell(30.0, 22.0)


class TestCellFromWinsize:
    def test_sane_winsize_yields_cell(self):
        assert show.cell_from_winsize(**SANE) == (10.0, 22.0)

    def test_garbage_winsize_yields_none(self):
        assert show.cell_from_winsize(**GARBAGE) is None

    def test_zero_pixels_yields_none(self):
        assert show.cell_from_winsize(ws_row=42, ws_col=192,
                                      ws_xpixel=0, ws_ypixel=0) is None

    def test_zero_rows_yields_none(self):
        assert show.cell_from_winsize(ws_row=0, ws_col=0,
                                      ws_xpixel=1920, ws_ypixel=924) is None


class TestResolveCell:
    """resolve_cell(primary, siblings) -> (cell_w, cell_h, source)"""

    def test_prefers_primary_when_plausible(self):
        cw, ch, src = show.resolve_cell(SANE, [GARBAGE])
        assert (cw, ch) == (10.0, 22.0)
        assert src == "pty"

    def test_borrows_from_sibling_when_primary_is_garbage(self):
        # The real fix: cell size is a property of the font, not the window, so a
        # sibling PTY of the same kitty reports the true cell even when ours lies.
        cw, ch, src = show.resolve_cell(GARBAGE, [GARBAGE, SANE])
        assert (cw, ch) == (10.0, 22.0)
        assert src == "sibling"

    def test_falls_back_to_default_when_nothing_is_plausible(self):
        cw, ch, src = show.resolve_cell(GARBAGE, [GARBAGE])
        assert (cw, ch) == show.DEFAULT_CELL
        assert src == "default"

    def test_default_is_itself_plausible(self):
        assert show.plausible_cell(*show.DEFAULT_CELL)
