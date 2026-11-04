// Click through the whole site in a headless phone browser and report anything broken.
//
//   node tools/smoke_test.js
//
// Serves the repo locally (with 404.html for unknown paths, like GitHub Pages), blocks archive.org so no
// audio downloads, and exits 1 on a failed check, a page error or a missing local file. Needs Playwright
// (npm i -g playwright, or set PW to its path). Run it before every push to main.
const fs = require('fs'), path = require('path'), http = require('http');
const { chromium, devices } = require(process.env.PW || 'playwright');

const ROOT = path.resolve(__dirname, '..');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.webp': 'image/webp',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.ico': 'image/x-icon', '.xml': 'application/xml', '.txt': 'text/plain' };
const server = http.createServer((req, res) => {
  let f = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
  if (!f.startsWith(ROOT) || !fs.existsSync(f)) { res.writeHead(404, { 'Content-Type': 'text/html' }); return res.end(fs.readFileSync(path.join(ROOT, '404.html'))); }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(res);
});

let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`); if (!ok) failed++; };

server.listen(0, async () => {
  const B = `http://127.0.0.1:${server.address().port}`, errors = [], missing = [];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  await ctx.route('https://archive.org/**', r => r.abort());
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort());
  const p = await ctx.newPage();
  p.setDefaultTimeout(8000);
  p.on('pageerror', e => errors.push(e.message));
  p.on('response', r => { if (r.url().startsWith(B) && r.status() >= 400 && !/\/(song|show|day)\/nope/.test(r.url())) missing.push(r.status() + ' ' + r.url()); });
  const at = () => new URL(p.url()).pathname, h2 = () => p.textContent('#detail h2'), wait = (ms = 900) => p.waitForTimeout(ms);
  const go = async url => { await p.goto(B + url); await wait(1500); };

  try {
    await go('/'); check('home opens a song', (await h2()).length > 0 && at() === '/');
    await go('/song/dark-star/'); check('song page', (await h2()) === 'Dark Star' && at() === '/song/dark-star/');
    await p.click('.song-button[data-song="Bertha"]'); await wait();
    check('pick a song from the list', (await h2()) === 'Bertha' && at() === '/song/bertha/');
    await p.click('#this-day'); await wait(); check('this day', at() === '/this-day/');
    await p.goBack(); await wait(); check('back from this day', (await h2()) === 'Bertha');

    await go('/day/10-31/'); check('day page', (await h2()) === 'October 31' && (await p.locator('.day-show').count()) > 5);
    await p.waitForSelector('#day-played'); check('songs played on this day', (await p.locator('.dp-chip:visible').count()) === 18 && (await p.locator('#dp-more').count()) === 1);
    await p.click('[data-day-step="1"]'); await wait(); check('next day', at() === '/day/11-01/');
    await p.fill('#day-pick', '2024-02-29'); await p.dispatchEvent('#day-pick', 'change'); await wait();
    check('pick a day (Feb 29)', at() === '/day/02-29/' && (await h2()) === 'February 29');


    await go('/song/dark-star/'); await p.waitForSelector('#plays:not([hidden])');
    check('every time they played it', (await p.locator('.py').count()) > 10 && (await p.locator('.py-chip.is-bust').count()) > 0);
    await p.click('.plays-long'); await wait(1200); check('longest tape track opens its show', at() === '/show/1973-12-06/');

    await go('/show/1977-05-08/');
    check('show page', (await p.locator('.tk-a-venue').textContent()).includes('Barton Hall'));
    await p.waitForSelector('.sl-row'); check('setlist with sets', (await p.locator('.sl-set').count()) >= 2);
    await p.locator('.sl-play', { hasText: 'Fire On The Mountain' }).click(); await wait(500);
    check('tap a setlist song plays it', (await p.locator('.sl-row.is-playing .sl-name').textContent()).includes('Fire'));
    await go('/show/1976-10-09/'); await p.waitForSelector('.sl-row');
    check('multi-tape setlist', (await p.locator('.sl-src').count()) > 0 && (await p.locator('.sl-row.is-missing').count()) === 0);

    await go('/song/dark-star/'); await p.locator('.tape.best [data-play-show]').click(); await wait(1200);
    check('Play Full Show goes to the show page', at() === '/show/1972-08-27/' && (await p.textContent('#now-type')) === 'FULL SHOW');
    await p.goBack(); await wait(); check('back from show', (await h2()) === 'Dark Star');

    await go('/'); await p.fill('#search', '7/7/89'); await wait(600); await p.press('#search', 'Enter'); await wait();
    check('search by date', at() === '/show/1989-07-07/');
    await p.fill('#search', 'pittsburgh'); await wait(600); check('search by city', (await p.locator('.show-button').count()) > 5);

    await go('/#Bertha'); check('old #song link', at() === '/song/bertha/');
    await go('/#show-1989-07-07'); check('old #show link', at() === '/show/1989-07-07/');
    await go('/#this-day'); check('old #this-day link', at() === '/this-day/');
    await go('/song/nope/'); check('unknown page falls back home', at() === '/');

    const nojs = await browser.newContext({ javaScriptEnabled: false }), q = await nojs.newPage();
    await q.goto(B + '/song/dark-star/');
    check('readable without JavaScript', (await q.textContent('#detail')).includes('first played Dark Star'));
    await q.goto(B + '/day/10-31/'); check('day page readable without JavaScript', (await q.textContent('#detail')).includes('12 shows'));
  } catch (e) { check('run', false, e.message.split('\n')[0]); }

  check('no page errors', !errors.length, errors.slice(0, 3).join(' / '));
  check('no missing files', !missing.length, missing.slice(0, 3).join(' / '));
  await browser.close(); server.close();
  console.log(failed ? `\n${failed} check(s) failed` : '\nAll checks passed');
  process.exit(failed ? 1 : 0);
});
