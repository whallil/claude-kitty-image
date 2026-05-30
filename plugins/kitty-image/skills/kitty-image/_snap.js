// Screenshot driver for html.py. Config arrives as JSON in $SNAP_CFG; the
// caller sets NODE_PATH so `require('puppeteer-core')` resolves from the cache.
// Exit codes: 0 ok | 40 launch failed | 41 navigation/screenshot failed |
// 42 selector not found. A short "SNAPERR[phase] message" goes to stderr.
const puppeteer = require('puppeteer-core');

(async () => {
  const cfg = JSON.parse(process.env.SNAP_CFG);
  let phase = 'launch';
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: cfg.chrome,
      args: ['--no-sandbox', '--disable-gpu'],
      headless: true,
    });
    const page = await browser.newPage();
    await page.setViewport({
      width: cfg.width,
      height: cfg.height,
      deviceScaleFactor: cfg.scale,
    });

    phase = 'navigate';
    await page.goto(cfg.url, { waitUntil: 'networkidle2', timeout: cfg.timeout });
    if (cfg.wait) {
      await new Promise((r) => setTimeout(r, cfg.wait));
    }

    if (cfg.selector) {
      phase = 'selector';
      await page.waitForSelector(cfg.selector, { timeout: cfg.timeout });
      const el = await page.$(cfg.selector);
      if (!el) throw new Error('selector matched no element: ' + cfg.selector);
      phase = 'shoot';
      await el.screenshot({ path: cfg.out });
    } else {
      phase = 'shoot';
      await page.screenshot({ path: cfg.out, fullPage: !!cfg.fullPage });
    }
  } catch (e) {
    process.stderr.write('SNAPERR[' + phase + '] ' + (e && e.message ? e.message : e) + '\n');
    process.exitCode = phase === 'selector' ? 42 : (phase === 'launch' ? 40 : 41);
  } finally {
    if (browser) {
      try { await browser.close(); } catch (_) { /* ignore */ }
    }
  }
})();
