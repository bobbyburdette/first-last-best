// Make "This day in Dead history" posts for Facebook and Instagram: one portrait card image and caption per day.
//
//   node tools/social/make_posts.js --start 2026-11-01 --days 30
//
// Writes tools/social/out/<date>.png, <date>.txt and posts.csv (date, image, caption) for Meta Business Suite.
// Needs Playwright (npm i -g playwright, or set PW to its path). Run from anywhere; reads the site's data files.
const fs = require('fs'), path = require('path'), http = require('http');
const { chromium } = require(process.env.PW || 'playwright');

const ROOT = path.resolve(__dirname, '../..'), OUT = path.join(__dirname, 'out');
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const songs = JSON.parse(fs.readFileSync(path.join(ROOT, 'songs.json')));
const shows = JSON.parse(fs.readFileSync(path.join(ROOT, 'shows.json')));
const setlists = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/setlists.json')));
const showByDate = Object.fromEntries(shows.map(s => [s.d, s]));

const slug = n => n.toLowerCase().replace(/&/g, ' and ').replace(/['’.]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const md = d => d.slice(5);
const dt = d => new Date(d + 'T12:00:00Z');
const fmt = (d, o) => dt(d).toLocaleDateString('en-US', { ...o, timeZone: 'UTC' });
const place = p => { const loc = (p.venue || '').split(' - '); return [p.venueName || loc[0], p.city || loc.slice(1).join(', ')]; };
const RANK = { best: 0, first: 1, last: 2 };
const KIND = { best: 'top-voted version on HeadyVersion', first: 'first time the Dead played it live', last: 'last time the Dead played it' };

const recent = []; // songs headlined in the last two weeks, so the feed doesn't repeat itself
const rankOf = n => songs.find(x => x.kind !== 'sequence' && [x.name, ...(x.aliases || [])].some(a => a.toLowerCase() === n.toLowerCase()))?.rank ?? 999;

function pick(day) {
  const hits = [];
  for (const s of songs) for (const k of ['first', 'last', 'best']) {
    const p = s[k];
    if (p?.date && md(p.date) === md(day)) hits.push({ s, k, p });
  }
  // Lead with the strongest story: famous songs first (Rolling Stone rank), Bests with real vote counts ahead.
  const score = h => (h.s.rank ?? 140) - (h.k === 'best' ? Math.min(40, (h.p.votes || 0) / 4) : 0) + RANK[h.k] * 3;
  hits.sort((a, b) => score(a) - score(b) || a.s.name.localeCompare(b.s.name));
  const fresh = hits.filter(h => !recent.includes(h.s.name));
  if (fresh.length) hits.unshift(fresh[0]);
  if (hits.length) {
    const h = hits[0], [venue, city] = place(h.p), same = hits.filter(x => x.p.date === h.p.date).length - 1;
    return { kind: h.k, date: h.p.date, venue, city, headline: h.s.short || h.s.name,
      line: `The ${KIND[h.k]}${h.k === 'best' && h.p.votes ? ` (${h.p.votes} votes)` : ''}.${same ? ` Plus ${same} more First, Last or Best from the same night.` : ''}`,
      url: `firstlastbest.com/show/${h.p.date}/`, song: h.s.name, more: hits.length - 1 };
  }
  // No First, Last or Best on this date: feature the show with the biggest song we haven't headlined lately.
  const cands = shows.filter(s => md(s.d) === md(day)).map(s => {
    const rows = (setlists[s.d]?.sets || []).flatMap(([, r]) => r).filter(r => r[1] >= 0);
    const star = rows.map(r => r[0]).filter(n => !recent.includes(n)).sort((a, b) => rankOf(a) - rankOf(b))[0];
    return { s, star, score: star ? rankOf(star) : 999 };
  }).filter(c => c.score < 999);
  if (!cands.length) return null;
  cands.sort((a, b) => a.score - b.score || a.s.d.localeCompare(b.s.d));
  const s = cands[0].s, rows = (setlists[s.d]?.sets || []).flatMap(([, r]) => r), star = cands[0].star;
  const onTape = rows.filter(r => r[1] >= 0).length;
  return { kind: 'show', date: s.d, venue: s.v, city: s.c, headline: star || s.v, song: star,
    line: rows.length ? `Opened with ${rows[0][0]}, closed with ${rows[rows.length - 1][0]}. ${onTape} songs on tape.` : 'The whole show, free from the tape.',
    url: `firstlastbest.com/show/${s.d}/` };
}

function caption(day, p) {
  const years = dt(day).getUTCFullYear() - Number(p.date.slice(0, 4));
  const when = `${fmt(p.date, { month: 'numeric', day: 'numeric', year: '2-digit' })} · ${p.venue}${p.city ? ', ' + p.city : ''}`;
  const lead = p.kind === 'show'
    ? `${years} years ago today, the Grateful Dead played ${p.venue}${p.song ? `, including ${p.song}` : ''}.`
    : `${years} years ago today: the ${p.kind === 'best' ? 'best' : p.kind} ${p.song}.`;
  return [lead, when, p.line, `Listen free: ${p.url}`, '#GratefulDead #ThisDayInDeadHistory'].join('\n');
}

const MIME = { '.html': 'text/html', '.webp': 'image/webp', '.woff2': 'font/woff2', '.png': 'image/png' };
(async () => {
  const start = arg('start', new Date().toISOString().slice(0, 10)), days = Number(arg('days', 7));
  fs.mkdirSync(OUT, { recursive: true });
  const server = http.createServer((req, res) => {
    const u = decodeURIComponent(req.url.split('?')[0]);
    const f = u.startsWith('/card/') ? path.join(__dirname, u.slice(6)) : path.join(ROOT, u);
    if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(res);
  }).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch(), page = await browser.newPage({ viewport: { width: 1080, height: 1350 } });
  await page.goto(base + '/card/card.html');
  const rows = [['date', 'image', 'caption']];
  for (let i = 0; i < days; i++) {
    const day = new Date(dt(start).getTime() + i * 864e5).toISOString().slice(0, 10), p = pick(day);
    if (!p) { console.log(day, 'nothing to post'); continue; }
    recent.push(p.song || p.headline); if (recent.length > 14) recent.shift();
    const show = showByDate[p.date] || {}, yearsAgo = dt(day).getUTCFullYear() - Number(p.date.slice(0, 4));
    const [y, m, d] = p.date.split('-');
    await page.evaluate(c => window.renderCard(c), {
      ...p, monthDay: fmt(day, { month: 'long', day: 'numeric' }), yearsAgo, code: `GD${y.slice(2)}${m}${d}`,
      short: `${+m}/${+d}/${y.slice(2)}`, when: fmt(p.date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase().replace(/,/g, ''),
      venue: p.venue || show.v, city: p.city || show.c });
    const img = `${day}.png`, text = caption(day, p);
    await page.screenshot({ path: path.join(OUT, img) });
    fs.writeFileSync(path.join(OUT, `${day}.txt`), text + '\n');
    rows.push([day, img, text]);
    console.log(day, p.kind, p.headline);
  }
  fs.writeFileSync(path.join(OUT, 'posts.csv'), rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n') + '\n');
  await browser.close(); server.close();
})();
