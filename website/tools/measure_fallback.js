/**
 * Measures the shipped webfonts against their local fallbacks so the
 * metric-matched @font-face rules in style.css can be regenerated.
 *
 *   node tools/measure_fallback.js            (needs playwright + a running server)
 *
 * Reported values are used as:
 *   size-adjust      = sizeAdjust
 *   ascent-override  = webAscent  / sizeAdjust
 *   descent-override = webDescent / sizeAdjust
 */
const { chromium } = require('playwright');

(async () => {
  const url = process.argv[2] || 'http://localhost:8099/';
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);

  const rows = await page.evaluate(() => {
    const sample = 'Cooked over fire. Remembered far longer. Handgloves 0123456789';
    const ctx = document.createElement('canvas').getContext('2d');
    const measure = family => {
      ctx.font = '100px ' + family;
      const t = ctx.measureText(sample);
      return { w: t.width, asc: t.fontBoundingBoxAscent / 100, desc: t.fontBoundingBoxDescent / 100 };
    };
    return [['"Cormorant Garamond"', 'Georgia'], ['Inter', 'Arial']].map(([web, fb]) => {
      const a = measure(web), b = measure(fb);
      const sizeAdjust = a.w / b.w;
      return {
        web, fallback: fb,
        'size-adjust': (sizeAdjust * 100).toFixed(1) + '%',
        'ascent-override': (a.asc / sizeAdjust * 100).toFixed(1) + '%',
        'descent-override': (a.desc / sizeAdjust * 100).toFixed(1) + '%'
      };
    });
  });
  console.table(rows);
  await browser.close();
})();
