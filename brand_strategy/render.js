// HTML -> PDF (Chromium, Playwright). Ishlatish: node render.js
// Muqova alohida (raqamsiz), qolgan sahifalar pastki raqam bilan; so'ng pdfunite bilan birlashtiriladi.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');
const out = (f) => path.join(__dirname, 'out', f);
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + out('strategy.html'), { waitUntil: 'networkidle' });
  await p.pdf({ path: out('_cover.pdf'), preferCSSPageSize: true, printBackground: true, pageRanges: '1' });
  await p.addStyleTag({ content: '.cover{display:none!important}' });
  await p.pdf({ path: out('_body.pdf'), preferCSSPageSize: true, printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: '<div style="width:100%;font-family:Inter,sans-serif;font-size:6.5px;color:#8a8a8a;letter-spacing:.12em;padding:0 11mm;display:flex;justify-content:space-between"><span>BOBUR · 30 KUNLIK STRATEGIYA</span><span class="pageNumber"></span></div>' });
  await b.close();
  execFileSync('pdfunite', [out('_cover.pdf'), out('_body.pdf'), out('BOBUR_30_kunlik_strategiya.pdf')]);
  fs.unlinkSync(out('_cover.pdf')); fs.unlinkSync(out('_body.pdf'));
})();
