import { chromium } from 'playwright';
const out = {};
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome-stable', headless: true });
const ctx = await browser.newContext({ userAgent: 'uniprot-link-research/0.1' });
const page = await ctx.newPage();
await page.goto('https://sparql.uniprot.org/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForTimeout(3500);
out.ui_title = await page.title();
out.ui_editor_nodes = await page.locator('.yasgui, .yasqe, .CodeMirror, textarea').count();
out.example_links = await page.locator('a').evaluateAll(els =>
  els.map(e => e.textContent.trim()).filter(t => t && t.length>4 && t.length<90)).then(a=>[...new Set(a)].slice(0,40));
await page.screenshot({ path: 'sparql-ui.png' });
const help = await ctx.newPage();
await help.goto('https://www.uniprot.org/help/sparql', { waitUntil: 'domcontentloaded', timeout: 60000 });
await help.waitForTimeout(2500);
out.help_title = await help.title();
out.help_text = (await help.locator('body').innerText()).replace(/\n{2,}/g,'\n').slice(0, 1500);
console.log(JSON.stringify(out, null, 2));
await browser.close();
