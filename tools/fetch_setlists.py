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
    # Songs the tape has in a different order: match by exact name to any unused track.
    used = {r[1] for _, rows in out for r in rows if r[1] >= 0}
    for _, rows in out:
        for r in rows:
            if r[1] < 0:
                j = next((j for j, key in enumerate(keys) if key == title_key(r[0]) and tape[j][0] not in used), None)
                if j is not None:
                    r[1], r[2] = tape[j][0], int(tape[j][2])
                    used.add(tape[j][0])
    return out


def hit_rate(sets):
    rows = [r for _, rs in sets for r in rs]
    return sum(r[1] >= 0 for r in rows) / len(rows) if rows else 0


def borrow_labels(tracks, labeled):
    """Copy song names onto an unlabeled tape from a labeled copy of the same show: each track takes the name of
    the labeled track playing at the same point in the show."""
    def spans(ts):
        lens = [flb.secs(t[2]) for t in ts]
        total, start, out = sum(lens), 0, []
        for n in lens:
            out.append((start / total, (start + n) / total) if total else (0, 0))
            start += n
        return out, total
    a, ta = spans(tracks)
    b, tb = spans(labeled)
    if not ta or not tb or abs(ta - tb) > 0.1 * tb:
        return None
    out = [list(t) for t in tracks]
    for i, (s0, s1) in enumerate(a):
        mid = (s0 + s1) / 2
        j = next((j for j, (b0, b1) in enumerate(b) if b0 <= mid < b1), None)
        if j is not None:
            out[i][1] = labeled[j][1]
    return out


def better_tape(date, sets, ident, tracks, rows):
    """Untitled or mislabeled tapes can't be matched. Keep the best-sounding tape and borrow song names from a
    labeled copy of the same show; only switch tapes when the other one sounds at least as good."""
    best = (hit_rate(rows), ident, None, rows)
    for u in sorted(flb.uploads_for_date(date), key=flb.rank_key)[:6]:
        alt = u['identifier']
        if alt == ident or flb.risky_source(alt):
            continue
        alt_tracks = tape_tracks(alt)
        if not alt_tracks:
            continue
        borrowed = borrow_labels(tracks, alt_tracks)
        options = [(ident, borrowed)] if borrowed else []
        if not flb.is_upgrade(alt, ident):
            options.append((alt, alt_tracks))
        for who, t in options:
            r = match(sets, t)
            if hit_rate(r) > best[0] + 0.1:
                best = (hit_rate(r), who, t, r)
    return best


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
            if hit_rate(rows) < 0.8:
                rate, who, new_tracks, new_rows = better_tape(date, sets, ident, tracks, rows)
                if new_tracks:
                    kind = 'relabeled' if who == ident else 'swapped'
                    ident, tracks, rows, stats[kind] = who, new_tracks, new_rows, stats.get(kind, 0) + 1
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
