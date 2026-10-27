"""Build data/setlists.json: each show's setlist (sets from The SetList Program) matched to the
tracks on the show's archive.org tape, so every song can be played from that night.

    python3 tools/fetch_setlists.py            # all shows (cached; first run takes ~40 minutes)
    python3 tools/fetch_setlists.py --refresh  # re-download setlists that weren't found before

Only set lists are read from setlists.net; comments and anything else on the page are ignored.
Then run tools/build_pages.py to put the setlists on the show pages.
"""
import argparse
import html
import json
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import flb

OUT = flb.ROOT / 'data' / 'setlists.json'
CACHE = flb.CACHE / 'setlists'
NON_SONG = re.compile(r'^(tuning|encore break|set ?break|crowd|applause|intro|banter|dead air|stage (announcements?|banter)'
                      r'|soundcheck|take a step back)\b', re.I)
SEGUE = re.compile(r'\s*(-?>|→)\s*$')


def title_key(t):
    """Same rules as titleKey() in app.js."""
    t = re.sub(r'\bsaint\b', 'st', t.lower())
    t = re.sub(r'\bthe\b|\band\b', '', t)
    t = re.sub(r'[^a-z0-9]', '', t).replace('ing', 'in')
    return re.sub(r's$', '', t)


def all_shows():
    dates = {s['d']: s['id'] for s in flb.load_shows()}
    for song in flb.load_songs():
        for k in ('first', 'last', 'best'):
            p = song.get(k) or {}
            if p.get('date') and p['date'] not in dates:
                dates[p['date']] = p.get('identifier')
    return dict(sorted(dates.items()))


def setlist_page(date, refresh=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f'{date}.html'
    if f.exists() and not (refresh and f.stat().st_size < 200):
        return f.read_text()
    y, m, d = date.split('-')
    url = 'https://www.setlists.net/?' + urllib.parse.urlencode({'search': 'true', 'month': int(m), 'day': int(d), 'year': y[2:]})
    try:
        text = flb.http_get(url)
    except Exception:
        text = ''
    f.write_text(text)
    time.sleep(1)  # be gentle with setlists.net
    return text


def parse_sets(page):
    """[(set name, [song, ...]), ...] when the page is a single show."""
    if '1 Show Found' not in page:
        return []
    body = page.split('Download/Listen', 1)[0]
    sets = []
    for name, chunk in re.findall(r'<b>((?:Set \d|Encore)[^<]*?):?</b><br>(.*?)(?=<p>|$)', body, re.S):
        songs = [html.unescape(s).strip() for s in re.split(r'<br>', chunk) if s.strip()]
        songs = [re.sub(r'<[^>]+>', '', s).strip() for s in songs]
        songs = [s for s in songs if s]
        if songs:
            sets.append((name.strip().rstrip(':'), songs))
    return sets


def tape_tracks(ident):
    if not ident:
        return []
    try:
        files = flb.mp3s(ident)
    except Exception:
        return []
    return [[f['name'], re.sub(r'^\s*\d{1,2}[\s.\-_]+', '', f.get('title') or f['name'][:-4]).strip(), f.get('length') or '']
            for f in files]


def match(sets, tracks):
    tape = [(i, SEGUE.sub('', t).strip(), bool(SEGUE.search(t))) for i, (_, t, _) in enumerate(tracks)
            if not NON_SONG.match(SEGUE.sub('', t).strip())]
    keys = [title_key(t) for _, t, _ in tape]
    out, pos = [], 0
    for name, songs in sets:
        rows = []
        for song in songs:
            k, hit = title_key(song), None
            for j in range(pos, min(pos + 6, len(tape))):
                if keys[j] == k or (len(k) > 3 and len(keys[j]) > 3 and (k in keys[j] or keys[j] in k)) \
                        or (len(k) >= 8 and keys[j][:8] == k[:8]):
                    hit = j
                    break
            if hit is None:
                rows.append([song, -1, 0])
            else:
                rows.append([song, tape[hit][0], int(tape[hit][2])])
                pos = hit + 1
        out.append([name, rows])
    return out


def tape_only(tracks):
    rows = [[SEGUE.sub('', t).strip(), i, int(bool(SEGUE.search(t)))] for i, (_, t, _) in enumerate(tracks)
            if not NON_SONG.match(SEGUE.sub('', t).strip())]
    return [['', rows]] if rows else []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--refresh', action='store_true')
    args = ap.parse_args()
    shows = all_shows()
    with ThreadPoolExecutor(4) as pool:
        tapes = dict(zip(shows, pool.map(tape_tracks, shows.values())))
    print(f'tapes: {sum(1 for t in tapes.values() if t)} of {len(shows)} have tracks', flush=True)
    data, stats = {}, {'sets': 0, 'tape_only': 0, 'none': 0}
    for n, (date, ident) in enumerate(shows.items(), 1):
        sets = parse_sets(setlist_page(date, args.refresh))
        tracks = tapes[date]
        if sets:
            rows, stats['sets'] = match(sets, tracks), stats['sets'] + 1
        elif tracks:
            rows, stats['tape_only'] = tape_only(tracks), stats['tape_only'] + 1
        else:
            stats['none'] += 1
            continue
        data[date] = {'id': ident if tracks else None, 'tracks': tracks, 'sets': rows, 'full': bool(sets)}
        if n % 100 == 0:
            print(f'{n}/{len(shows)} {stats}', flush=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'{OUT.relative_to(flb.ROOT)}: {len(data)} shows {stats}')


if __name__ == '__main__':
    main()
