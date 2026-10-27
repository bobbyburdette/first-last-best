"""Write a crawlable page for every song and show, plus sitemap.xml and 404.html.

Each page is index.html with its own title, description, structured data and a plain-text
summary of the answer (first, last and best versions), so search engines and AI crawlers that
don't run JavaScript can read it. The app replaces the summary as soon as it loads.

    python3 tools/build_pages.py          # rebuild everything
    python3 tools/build_pages.py --check  # exit 1 if any page is out of date

Run it after any change to index.html, app.js, style.css, songs.json or shows.json.
"""
import argparse
import datetime
import html
import json
import re
import shutil
import sys

import flb
from fetch_setlists import OUT as SETLISTS, title_key

SITE = 'https://firstlastbest.com'
TEMPLATE = flb.ROOT / 'index.html'
KIND = {'first': 'First time played live', 'last': 'Last time played', 'best': 'Top-voted version on HeadyVersion'}


def esc(v):
    return html.escape(str(v), quote=True)


def slug(name):
    n = re.sub(r"['’.]", '', name.lower().replace('&', ' and '))
    return re.sub(r'[^a-z0-9]+', '-', n).strip('-')


def dt(d):
    return datetime.date.fromisoformat(d)


def long_date(d):
    x = dt(d)
    return f'{x:%B} {x.day}, {x.year}'


def short_date(d):
    x = dt(d)
    return f'{x.month}/{x.day}/{x:%y}'


def place(p):
    loc = (p.get('venue') or '').split(' - ')
    return p.get('venueName') or loc[0], p.get('city') or ', '.join(loc[1:])


def where(venue, city):
    return f'{venue} in {city}' if city else venue


def song_url(s):
    return f'/song/{slug(s["name"])}/'


def show_url(d):
    return f'/show/{d}/'


def venue_key(v, c):
    city = re.sub(r'[^a-z0-9]', '', (c or '').split(',')[0].lower())
    k = re.sub(r'[^a-z0-9]', '', re.split(r' - |,|\(', v or '')[0].lower().replace('theatre', 'theater'))
    for a, b in ((r'johnfkennedy', 'jfk'), (r'oaklandalamedacounty|alamedacounty', 'oakland'),
                 (r'henryjkaiser(conventioncenter|auditorium)', 'kaiser'), (r'^the', ''), (r'(earlyshow|lateshow)$', '')):
        k = re.sub(a, b, k)
    if city and k != city and k.startswith(city):
        k = k[len(city):]
    return city + '|' + k


# ---------- data ----------

def build_shows(songs):
    by_date = {s['d']: {**s, 'picks': []} for s in flb.load_shows()}
    for song in songs:
        for k in ('first', 'last', 'best'):
            p = song.get(k) or {}
            if not p.get('date'):
                continue
            if p['date'] not in by_date:
                v, c = place(p)
                by_date[p['date']] = {'d': p['date'], 'v': v, 'c': c, 'id': p.get('identifier'), 'picks': []}
            by_date[p['date']]['picks'].append((song, k))
    shows = sorted(by_date.values(), key=lambda s: s['d'])
    for s in shows:
        s['picks'].sort(key=lambda x: (['first', 'last', 'best'].index(x[1]), x[0]['name']))
        s['vk'] = venue_key(s['v'], s['c'])
    return shows


# ---------- page content ----------

def show_link(d, text=None):
    return f'<a href="{show_url(d)}">{esc(text or long_date(d))}</a>'


def song_page(song):
    name = song['name']
    f, l, b = (song.get(k) or {} for k in ('first', 'last', 'best'))
    lines, desc = [], []
    if f.get('date'):
        v, c = place(f)
        lines.append(('First time played', f'The Grateful Dead first played {esc(name)} live on '
                      f'{show_link(f["date"])} at {esc(where(v, c))}.'))
        desc.append(f'first played {short_date(f["date"])} at {v}')
    else:
        lines.append(('First time played', 'There is no verified date for the first live performance.'))
    if l.get('date'):
        v, c = place(l)
        lines.append(('Last time played', f'The last time they played it was {show_link(l["date"])} '
                      f'at {esc(where(v, c))}.'))
        desc.append(f'last played {short_date(l["date"])}')
    else:
        lines.append(('Last time played', 'There is no verified date for the last live performance.'))
    if b.get('date'):
        v, c = place(b)
        votes = f', with {b["votes"]} votes' if b.get('votes') else ''
        when = f' (as of {dt(b["checkedAt"]):%B %Y})' if b.get('checkedAt') else ''
        text = (f'The top-voted version on HeadyVersion is {show_link(b["date"])} at '
                f'{esc(where(v, c))}{votes}{when}.')
        runners = [r for r in b.get('runnersUp') or [] if r.get('date')]
        if runners:
            text += ' Next in the voting: ' + ' and '.join(
                f'{show_link(r["date"], short_date(r["date"]))} ({r["votes"]} votes)' for r in runners) + '.'
        lines.append(('Best version', text))
        desc.append(f'fan-favorite version from {short_date(b["date"])}')
    years = [p['date'][:4] for p in (f, l) if p.get('date')]
    count = (f' It appears in {song["count"]} concert listings in The SetList Program, '
             f'{years[0]} to {years[-1]}.') if song.get('count') and len(years) == 2 else ''
    body = (f'<div class="seo-summary"><p class="song-kicker">THE GRATEFUL DEAD</p><h2>{esc(name)}</h2>'
            f'<p>The first, last and best live versions of {esc(name)} by the Grateful Dead, '
            f'with free recordings from the Internet Archive.{count}</p>'
            + ''.join(f'<h3>{h}</h3><p>{t}</p>' for h, t in lines) + '</div>')
    description = f'{name} by the Grateful Dead: ' + ', '.join(desc) + '. Stream all three free.'
    ld = {'@context': 'https://schema.org', '@type': 'MusicComposition', 'name': name,
          'url': SITE + song_url(song), 'description': description}
    if f.get('date'):
        v, c = place(f)
        ld['firstPerformance'] = event_ld(f['date'], v, c)
    return {'path': song_url(song), 'title': f'{name}: First, Last & Best Grateful Dead Versions',
            'description': description, 'body': body, 'ld': ld}


def event_ld(d, v, c):
    loc = {'@type': 'Place', 'name': v}
    if c:
        loc['address'] = {'@type': 'PostalAddress', 'addressLocality': c}
    return {'@type': 'MusicEvent', 'name': f'Grateful Dead at {v}', 'startDate': d, 'location': loc,
            'performer': {'@type': 'MusicGroup', 'name': 'Grateful Dead'}}


def setlist_html(sl, song_by_key):
    out = []
    for name, rows in sl['sets']:
        parts = []
        for i, (title, _, seg) in enumerate(rows):
            song = song_by_key.get(title_key(title))
            parts.append((f'<a href="{song_url(song)}">{esc(title)}</a>' if song else esc(title))
                         + ((' &gt; ' if seg else ', ') if i + 1 < len(rows) else ''))
        out.append(f'<p>{"<strong>" + esc(name) + ":</strong> " if name else ""}{"".join(parts)}</p>')
    return '<h3>Setlist</h3>' + ''.join(out)


def show_page(show, prev, nxt, same_venue, sl, song_by_key):
    d, v, c = show['d'], show['v'], show['c']
    picks = show['picks']
    if picks:
        items = ''.join(f'<li><a href="{song_url(s)}">{esc(s["name"])}</a>: {KIND[k]}</li>' for s, k in picks)
        part = f'<h3>First, Last and Best from this show</h3><ul>{items}</ul>'
        names = [s.get('short') or s['name'] for s, _ in picks]
        tail = names[0] if len(names) == 1 else ', '.join(names[:3]) + (f' and {len(names) - 3} more' if len(names) > 3 else '')
        description = (f'Grateful Dead at {where(v, c)} on {long_date(d)}. '
                       f'First, Last or Best versions from this show: {tail}. Stream the full show free.')
    else:
        part = '<p>None of the First, Last or Best versions on this site come from this show.</p>'
        description = f"Stream the Grateful Dead's {long_date(d)} show at {where(v, c)}, free from the Internet Archive."
    rec = (f'<p>Full recording: <a href="https://archive.org/details/{esc(show["id"])}">Internet Archive</a>.</p>'
           if show.get('id') else '')
    also = (f'<h3>More shows at {esc(v)}</h3><p>' + ', '.join(show_link(x['d'], short_date(x['d'])) for x in same_venue) + '</p>'
            if same_venue else '')
    nav = ' · '.join(x for x in (prev and f'Previous show: {show_link(prev["d"])}', nxt and f'Next show: {show_link(nxt["d"])}') if x)
    played = [t for _, rows in (sl or {}).get('sets', []) for t, _, _ in rows]
    if played:
        opener = ', '.join(played[:3])
        description = (f'Grateful Dead setlist for {long_date(d)} at {where(v, c)}, opening with {opener}. '
                       + (f'Best versions: {", ".join([(s.get("short") or s["name"]) for s, k in picks if k == "best"][:3])}. ' if any(k == 'best' for _, k in picks) else '')
                       + 'Play every song free from the tape.')
    body = (f'<div class="seo-summary"><p class="song-kicker">GRATEFUL DEAD CONCERT</p><h2>{esc(long_date(d))}</h2>'
            f'<p>The Grateful Dead played {esc(where(v, c))} on {dt(d):%A}, {esc(long_date(d))}.</p>'
            f'{setlist_html(sl, song_by_key) if played else ""}{part}{rec}{also}<p>{nav}</p></div>')
    ld = {'@context': 'https://schema.org', **event_ld(d, v, c), 'url': SITE + show_url(d), 'description': description}
    if played:
        ld['workPerformed'] = [{'@type': 'MusicComposition', 'name': t} for t in dict.fromkeys(played)]
    title = f'Grateful Dead {short_date(d)}{" Setlist" if played else ""} · {where(v, c)}'
    return {'path': show_url(d), 'song_list': False, 'title': title, 'description': description, 'body': body, 'ld': ld,
            'data': sl}


# ---------- template ----------

def song_list_html(songs):
    rows = sorted(songs, key=lambda s: s['name'])
    return ''.join(f'<a class="song-button" href="{song_url(s)}"><span class="num">{i:02d}</span>'
                   f'<span class="song-name">{esc(s.get("short") if s.get("kind") == "sequence" else s["name"])}</span></a>'
                   for i, s in enumerate(rows, 1))


NAV = r'<nav id="songs" aria-label="Song collection">.*?</nav>'
NAV_EMPTY = '<nav id="songs" aria-label="Song collection"><p>Loading songs…</p></nav>'


def sub(text, pattern, repl):
    new, n = re.subn(pattern, lambda m: repl, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f'template pattern not found: {pattern}')
    return new


def render(template, page):
    t = template
    url = SITE + page['path']
    t = sub(t, r'<title>.*?</title>', f'<title>{esc(page["title"])}</title>')
    t = sub(t, r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{esc(page["description"])}">')
    t = sub(t, r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">')
    t = sub(t, r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{esc(page["title"])}">')
    t = sub(t, r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{esc(page["description"])}">')
    t = sub(t, r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{url}">')
    ld = json.dumps(page['ld'], ensure_ascii=False).replace('</', '<\\/')
    t = sub(t, r'<script type="application/ld\+json">.*?</script>', f'<script type="application/ld+json">{ld}</script>')
    t = re.sub(r'(<section class="song-detail" id="detail" aria-live="polite">).*?(</section></div>)',
               lambda m: m.group(1) + page['body'] + m.group(2), t, count=1, flags=re.S)
    if not page.get('song_list', True):
        t = sub(t, NAV, NAV_EMPTY)
    return t.replace('<!doctype html>', '<!doctype html><!-- Generated by tools/build_pages.py from index.html. Do not edit. -->', 1)


def write(path, text, changed):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
        changed.append(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='report stale pages without writing')
    args = ap.parse_args()

    songs = flb.load_songs()
    template = TEMPLATE.read_text()
    template = sub(template, NAV, '<nav id="songs" aria-label="Song collection">' + song_list_html(songs) + '</nav>')
    if not re.search(r'<section class="song-detail" id="detail" aria-live="polite">.*?</section></div>', template, re.S):
        raise SystemExit('template: #detail section not found')

    shows = build_shows(songs)
    setlists = json.loads(SETLISTS.read_text()) if SETLISTS.exists() else {}
    song_by_key = {title_key(n): s for s in songs if s.get('kind') != 'sequence' for n in [s['name'], *s.get('aliases', [])]}
    by_venue = {}
    for s in shows:
        by_venue.setdefault(s['vk'], []).append(s)

    pages = [song_page(s) for s in songs]
    for i, s in enumerate(shows):
        same = [x for x in by_venue[s['vk']] if x is not s]
        pages.append(show_page(s, shows[i - 1] if i else None, shows[i + 1] if i + 1 < len(shows) else None, same,
                               setlists.get(s['d']), song_by_key))
    pages.append({'path': '/this-day/', 'title': 'This Day in Grateful Dead History | First Last Best',
                  'description': 'Grateful Dead songs first played, last played or at their best on this date, plus every show played on this day.',
                  'body': '<div class="seo-summary"><p class="song-kicker">THIS DAY IN DEAD HISTORY</p><h2>This day in Dead history</h2>'
                          '<p>Songs the Grateful Dead first played, last played or played best on today’s date, in any year, '
                          'plus every show they played on this day.</p></div>',
                  'ld': {'@context': 'https://schema.org', '@type': 'WebPage', 'name': 'This Day in Grateful Dead History',
                         'url': SITE + '/this-day/'}})

    expected, changed = {}, []
    expected[flb.ROOT / 'index.html'] = template
    for p in pages:
        expected[flb.ROOT / p['path'].strip('/') / 'index.html'] = render(template, p)
        if p.get('data'):
            expected[flb.ROOT / p['path'].strip('/') / 'setlist.json'] = json.dumps(p['data'], ensure_ascii=False, separators=(',', ':'))
    nf = render(template, {**pages[-1], 'path': '/', 'title': 'Page not found | First Last Best'})
    expected[flb.ROOT / '404.html'] = nf.replace('<link rel="canonical"', '<meta name="robots" content="noindex"><link rel="canonical"', 1)
    urls = ['/', '/this-day/'] + [p['path'] for p in pages if p['path'] != '/this-day/']
    expected[flb.ROOT / 'sitemap.xml'] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                                         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                         + ''.join(f'  <url><loc>{SITE}{u}</loc></url>\n' for u in urls) + '</urlset>\n')

    stale_dirs = []
    for d in ('song', 'show'):
        root = flb.ROOT / d
        if root.exists():
            stale_dirs += [x for x in root.iterdir() if x / 'index.html' not in expected]

    if args.check:
        bad = [p for p, t in expected.items() if not p.exists() or p.read_text() != t]
        for p in bad + stale_dirs:
            print('stale:', p.relative_to(flb.ROOT))
        print(f'{len(bad) + len(stale_dirs)} stale of {len(expected)} files')
        sys.exit(1 if bad or stale_dirs else 0)

    for x in stale_dirs:
        shutil.rmtree(x)
    for p, t in expected.items():
        write(p, t, changed)
    print(f'{len(pages)} pages ({len(songs)} songs, {len(shows)} shows), {len(changed)} files written, '
          f'{len(stale_dirs)} removed')


if __name__ == '__main__':
    main()
