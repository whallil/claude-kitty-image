import show

# Terminal geometry used across cases: 192 cols x 45 rows, cell 10x22 px.
# fit_cells now takes the resolved cell size directly rather than raw winsize
# pixels, because the PTY's pixel fields cannot be trusted (see test_cell_metrics).
WS = dict(ws_row=45, ws_col=192, cell_w=10.0, cell_h=22.0)


def fit(w, h, fit_height=True):
    return show.fit_cells(w, h, WS["ws_row"], WS["ws_col"],
                          WS["cell_w"], WS["cell_h"], fit_height=fit_height)


def test_small_image_native_both_modes():
    # 240x120 px -> 24 cols x 6 rows; fits, so unchanged in either mode.
    assert fit(240, 120, fit_height=True) == (24, 6)
    assert fit(240, 120, fit_height=False) == (24, 6)


def test_fit_height_downscales_tall_image():
    # 400x2970 px native ~ 40c x 135r; avail_r = 45-2 = 43 -> must shrink.
    # (DRIFT_MARGIN is gone: placeholder cells anchor the image, so no over-reserve.)
    c, r = fit(400, 2970, fit_height=True)
    assert r <= 43 and c <= 191
    assert r >= 1 and c >= 1


def test_scroll_keeps_tall_image_native_uncapped():
    # Tall-narrow fits width (40c <= 191), so scroll mode keeps it native and
    # does NOT cap the height at the screen.
    assert fit(400, 2970, fit_height=False) == (40, 135)


def test_scroll_downscales_only_when_wider_than_terminal():
    # 4000x8000 px ~ 400c x 364r. Wider than avail 191 -> scale = 191/400; the
    # height scales by the SAME factor and is NOT capped at the screen:
    # round(364 * 0.4775) = 174 (a hard regression guard for "uncapped height").
    assert fit(4000, 8000, fit_height=False) == (191, 174)


def test_scroll_never_upscales():
    # A small image stays its native size; width is not stretched to 191.
    assert fit(100, 100, fit_height=False)[0] < 191


def test_scroll_caps_height_at_the_diacritic_limit():
    # 400 x 20000 px -> 910 native rows, but only 297 are addressable by a
    # placeholder diacritic. Must scale down rather than emit an unrenderable grid.
    c, r = fit(400, 20000, fit_height=False)
    assert r <= show.MAX_GRID
    assert c >= 1


def test_bad_geometry_returns_unit():
    assert show.fit_cells(240, 120, 0, 0, 0, 0) == (1, 1)
    assert show.fit_cells(0, 0, 45, 192, 10.0, 22.0) == (1, 1)


def test_garbage_winsize_no_longer_collapses_the_image():
    # Regression: with the real garbage this PTY reports (cell 255.5 x 1553.3),
    # the old code returned (4, 1) for a 900x408 image. resolve_cell now rejects
    # it and borrows a sibling's 10x22, giving a sane box.
    garbage = dict(ws_row=42, ws_col=192, ws_xpixel=49049, ws_ypixel=65238)
    sane = dict(ws_row=42, ws_col=192, ws_xpixel=1920, ws_ypixel=924)
    cell_w, cell_h, source = show.resolve_cell(garbage, [sane])
    assert source == "sibling"
    assert show.fit_cells(900, 408, 42, 192, cell_w, cell_h) == (90, 19)
