// Print an HTML page to an A4 PDF with Chromium. Usage: node render_pdf.js <in.html> <out.pdf> [preview.png]
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const [inp, out, png] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 794, height: 1123 } });
  await page.goto('file://' + path.resolve(inp), { waitUntil: 'networkidle' });
  await page.pdf({ path: out, format: 'A4', printBackground: true, preferCSSPageSize: true });
  if (png) await page.screenshot({ path: png, fullPage: true });
  const overflow = await page.evaluate(() => {
    const p = document.querySelector('.page');
    return { scroll: p.scrollHeight, client: p.clientHeight };
  });
  console.log('saved', out, JSON.stringify(overflow));
  await browser.close();
})();
