"""Unicode placeholder cells: the text that makes a virtual placement visible.

Kitty renders a virtual placement (a=T,U=1) only where U+10EEEE cells appear in
the text stream. Each cell carries its (row, col) as combining diacritics and the
image id as a 24-bit foreground colour. Because those cells are ordinary text,
they live in Claude Code's committed transcript and scroll with it -- which is
the whole reason this path replaces direct-paint.

Compactness is a hard requirement, not a nicety: a naive grid that repeats both
diacritics on every cell emitted ~45KB for a full-size image and tripped Claude's
output cap. Kitty auto-increments the column (and reuses the row) when the
diacritics are omitted, so only the first cell of each row needs them.
"""
import re

import show

PH = "\U0010eeee"


class TestDiacritics:
    def test_table_has_297_entries(self):
        # Kitty's rowcolumn-diacritics.txt (Unicode 6.0.0) -- caps a grid at 297.
        assert len(show.DIACRITICS) == 297

    def test_first_entries_match_kitty(self):
        assert show.DIACRITICS[:5] == [0x0305, 0x030D, 0x030E, 0x0310, 0x0312]

    def test_all_are_combining_marks(self):
        import unicodedata
        for cp in show.DIACRITICS:
            assert unicodedata.combining(chr(cp)) != 0


class TestImageId:
    def test_id_fits_24_bits_and_is_nonzero(self):
        for data in (b"a", b"hello world", bytes(range(256))):
            i = show.image_id_for(data)
            assert 0 < i < (1 << 24)

    def test_id_is_stable_for_same_bytes(self):
        assert show.image_id_for(b"abc") == show.image_id_for(b"abc")

    def test_id_differs_for_different_bytes(self):
        # Distinct ids let two images coexist without clobbering each other.
        assert show.image_id_for(b"abc") != show.image_id_for(b"xyz")


class TestPlaceholderGrid:
    def test_emits_one_line_per_row(self):
        lines = show.placeholder_grid(0x0A0B0C, cols=40, rows=8).splitlines()
        assert len(lines) == 8

    def test_each_line_has_exactly_cols_placeholder_cells(self):
        for line in show.placeholder_grid(0x0A0B0C, cols=40, rows=8).splitlines():
            assert line.count(PH) == 40

    def test_encodes_image_id_as_truecolor_foreground(self):
        line = show.placeholder_grid(0x0A0B0C, cols=4, rows=1).splitlines()[0]
        assert line.startswith("\x1b[38;2;10;11;12m")
        assert line.endswith("\x1b[0m")

    def test_first_cell_of_each_row_carries_row_and_col_diacritics(self):
        lines = show.placeholder_grid(0x0A0B0C, cols=4, rows=3).splitlines()
        for r, line in enumerate(lines):
            body = re.sub(r"\x1b\[[0-9;]*m", "", line)
            assert body[1] == chr(show.DIACRITICS[r])   # row diacritic
            assert body[2] == chr(show.DIACRITICS[0])   # col 0 diacritic

    def test_later_cells_are_bare_so_column_auto_increments(self):
        body = re.sub(r"\x1b\[[0-9;]*m", "",
                      show.placeholder_grid(0x0A0B0C, cols=4, rows=1).splitlines()[0])
        assert body[3:] == PH * 3   # cells 1..3: no diacritics at all

    def test_stays_compact_at_full_screen_size(self):
        # The regression that killed the previous attempt: a full-size grid must
        # not approach Claude's output cap. 191x40 is about as big as it gets.
        # Measured in CHARACTERS -- that is what the cap counts, and U+10EEEE is
        # unavoidably 4 bytes of UTF-8 regardless of how we encode positions.
        grid = show.placeholder_grid(0x0A0B0C, cols=191, rows=40)
        assert len(grid) < 12_000

    def test_auto_increment_beats_per_cell_diacritics(self):
        # The actual property under test: positions are implied, not repeated.
        # A naive grid spends 3 chars/cell (placeholder + row + col diacritic);
        # ours spends 1 for every cell after the first in each row.
        cols, rows = 191, 40
        grid = show.placeholder_grid(0x0A0B0C, cols=cols, rows=rows)
        naive_cells = cols * rows * 3
        assert grid.count(PH) == cols * rows        # every cell still present
        assert len(grid) < naive_cells * 0.5        # at well under half the cost

    def test_rejects_grid_larger_than_the_diacritic_table(self):
        # Only 297 rows/cols are addressable; silently truncating would misrender.
        import pytest
        with pytest.raises(ValueError):
            show.placeholder_grid(0x0A0B0C, cols=4, rows=298)
        with pytest.raises(ValueError):
            show.placeholder_grid(0x0A0B0C, cols=298, rows=4)
