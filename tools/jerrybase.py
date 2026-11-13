"""Read JerryBase data and compare it with the site's.

JerryBase files live in the private archive repo (first-last-best-archive/incoming/jerrybase/): the
"Events by year" CSV downloads (Date, Venue, Band, Songs) and categories.csv (Public/Private/Canceled).
Only Public Grateful Dead events count as concerts. Soundcheck segments don't count as played live.

    python3 tools/jerrybase.py ../first-last-best-archive            # report: what JerryBase would change
    python3 tools/jerrybase.py ../first-last-best-archive --json OUT # write the parsed concerts as JSON
"""
import argparse
import collections
import csv
import json
import re
from pathlib import Path

import flb
from fetch_setlists import title_key

LABEL = re.compile(r'((?:(?:Partial|Acoustic|Electric|Early|Late) )*(?:Set \d+|Encore(?: \d+)?|Soundcheck|Show|Session|Set|'
                   r'Known Songs|Acoustic|Electric)):\s+')
NOT_LIVE = re.compile(r'Soundcheck|Session')
UNKNOWN = re.compile(r'^(unidentified|jam$|see shnid|then )', re.I)


def parse_songs(text):
    """'Set 1:  A, B > CSet 2:  D' -> [('Set 1', [['A', 0], ['B', 1], ['C', 0]]), ('Set 2', [['D', 0]])]
    (1 = segue into the next song)."""
    parts = LABEL.split(text)
    sets = []
    if parts[0].strip():
        parts = ['Show'] + parts if not LABEL.match(text) else parts[1:]
    else:
        parts = parts[1:]
    for label, body in zip(parts[0::2], parts[1::2]):
        rows = []
        for chunk in re.split(r',\s*', body):
            names = [n.strip() for n in re.split(r'\s*>\s*', chunk)]
            for i, n in enumerate(names):
                if n:
                    rows.append([n, int(i < len(names) - 1)])
        sets.append((label, rows))
    return sets


def load(archive):
    inc = Path(archive) / 'incoming' / 'jerrybase'
    cats = collections.defaultdict(set)
    for c in csv.DictReader(open(inc / 'categories.csv', encoding='utf-8')):
        cats[(c['date'], c['band'], c['venue'])].add((c['category'], c['show_id']))
    shows = {}
    for f in sorted(inc.glob('events-*.csv')):
        for r in csv.DictReader(open(f, encoding='utf-8-sig')):
            if r['Band'] != 'Grateful Dead':
                continue
            date = r['Date'][:10]
            got = cats.get((date, r['Band'], r['Venue']), set())
            if {c for c, _ in got} != {'Public'} or date.endswith('-00'):
                continue
            sets = [(l, rows) for l, rows in parse_songs(r['Songs'])] if r['Songs'].strip() else []
            live = [(l, [x for x in rows if not UNKNOWN.match(x[0])]) for l, rows in sets if not NOT_LIVE.search(l)]
            show = shows.setdefault(date, {'date': date, 'venue': r['Venue'], 'sets': [], 'partial': False,
                                           'jerrybase_ids': sorted({i for _, i in got if i})})
            if show['venue'] != r['Venue']:
                show['venue'] += ' / ' + r['Venue']
            show['sets'] += [[l, rows] for l, rows in live if rows]
            show['partial'] = show['partial'] or any(l.startswith('Partial') or l == 'Known Songs' for l, _ in sets)
    return shows


def report(shows):
    ours = {s['d']: s for s in flb.load_shows()}
    songs = flb.load_songs()
    played = collections.defaultdict(list)
    for d, s in sorted(shows.items()):
        seen = set()
        for _, rows in s['sets']:
            for n, _ in rows:
                k = title_key(n)
                if k not in seen:
                    seen.add(k)
                    played[k].append(d)
    with_sets = [d for d, s in shows.items() if s['sets']]
    print(f'JerryBase: {len(shows)} public Grateful Dead shows, {len(with_sets)} with setlists.')
    missing = sorted(set(shows) - set(ours))
    print(f'Shows JerryBase has that the site lacks: {len(missing)}')
    extra = sorted(set(ours) - set(shows))
    print(f'Show dates on the site JerryBase has no public show for: {len(extra)} {extra}')
    print('\nFirst/Last/count changes (JerryBase public concerts vs. the site):')
    for s in sorted(songs, key=lambda s: s['name']):
        if s.get('kind') == 'sequence':
            continue
        keys = {title_key(n) for n in flb.song_names(s)}
        dates = sorted({d for k in keys for d in played.get(k, [])})
        if not dates:
            print(f"  {s['name']}: not found in JerryBase")
            continue
        f, l = (s.get('first') or {}).get('date'), (s.get('last') or {}).get('date')
        notes = []
        if f != dates[0]:
            notes.append(f'First {f} -> {dates[0]}')
        if l != dates[-1]:
            notes.append(f'Last {l} -> {dates[-1]}')
        if s.get('count') and abs(len(dates) - s['count']) > max(2, s['count'] * .05):
            notes.append(f"count {s['count']} -> {len(dates)}")
        if notes:
            print(f"  {s['name']}: " + '; '.join(notes))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('archive')
    ap.add_argument('--json')
    args = ap.parse_args()
    shows = load(args.archive)
    if args.json:
        Path(args.json).write_text(json.dumps(shows, ensure_ascii=False, indent=0))
    else:
        report(shows)


if __name__ == '__main__':
    main()
