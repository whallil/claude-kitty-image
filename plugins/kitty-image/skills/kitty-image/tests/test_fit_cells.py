import show

# Terminal geometry used across cases: 192 cols x 45 rows, cell 10x22 px.
WS = dict(ws_row=45, ws_col=192, ws_xpixel=1920, ws_ypixel=990)  # cell_w=10, cell_h=22


def fit(w, h, fit_height=True):
    return show.fit_cells(w, h, WS["ws_row"], WS["ws_col"],
                          WS["ws_xpixel"], WS["ws_ypixel"], fit_height=fit_height)


def test_small_image_native_both_modes():
    # 240x120 px -> 24 cols x 6 rows; fits, so unchanged in either mode.
    assert fit(240, 120, fit_height=True) == (24, 6)
    assert fit(240, 120, fit_height=False) == (24, 6)


def test_fit_height_downscales_tall_image():
    # 400x2970 px native ~ 40c x 135r; avail_r = 45-2-6 = 37 -> must shrink.
    c, r = fit(400, 2970, fit_height=True)
    assert r <= 37 and c <= 191
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


def test_bad_geometry_returns_unit():
    assert show.fit_cells(240, 120, 0, 0, 0, 0) == (1, 1)
    assert show.fit_cells(0, 0, 45, 192, 1920, 990) == (1, 1)
