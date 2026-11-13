"""Make JerryBase the setlist source for every public Grateful Dead concert it lists.

    python3 tools/merge_jerrybase.py ../first-last-best-archive            # dry run: what would change
    python3 tools/merge_jerrybase.py ../first-last-best-archive --apply    # write data/setlists.json, shows.json

For each JerryBase concert with a setlist:
  - a show the site already has: its sets (order, set breaks, segues) come from JerryBase and are matched again
    to the same tape tracks. If JerryBase's setlist matches clearly fewer tracks than the old one, the old
    setlist is kept and the date is listed for a person to look at.
  - a show the site lacks: it is added. archive.org is searched for a tape (same preference as the rest of the
    site); without one the show gets a setlist and no tape.
Shows JerryBase doesn't list as public concerts are left as they are. First/Last picks are not touched.
Run after tools/fetch_setlists.py, which rebuilds setlists from The SetList Program.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import flb
import jerrybase
from fetch_setlists import OUT as SETLISTS, match, tape_only, tape_tracks, title_key

T = {flb.SBD: 'sbd', flb.MATRIX: 'mtx', flb.AUD: 'aud', flb.UNKNOWN: 'unk'}


def clean_label(label):
    """'Partial Show' / 'Show' / 'Known Songs' -> '' (no heading); 'Partial Set 2' -> 'Set 2'."""
    label = label.replace('Partial ', '').strip()
    return '' if label in ('Show', 'Known Songs', 'Set') else label.replace(': Set', ', set')


def jb_sets(show):
    return [(clean_label(l), rows) for l, rows in show['sets']]


def matched(sets):
    return sum(1 for _, rows in sets for r in rows if r[1] >= 0)


def same(a, b):
    a, b = title_key(a), title_key(b)
    return a == b or (min(len(a), len(b)) > 6 and (a in b or b in a))


def apply_jb(sets, tracks, old=()):
    """Match JerryBase sets to tape tracks; segue flags come from JerryBase. A song the old setlist had found
    on the tape (often on a second tape, far from where the matcher looks) keeps that track."""
    rows = match([(l, [n for n, _ in r]) for l, r in sets], [tr[:3] for tr in tracks]) if tracks else \
        [[l, [[n, -1, 0] for n, _ in r]] for l, r in sets]
    if tracks and old:
        used = {o[1] for _, out in rows for o in out if o[1] >= 0}
        prev = [(r[0], r[1]) for _, rs in old for r in rs if r[1] >= 0]
        for _, out in rows:
            for o in out:
                if o[1] < 0:
                    hit = next((i for n, i in prev if i not in used and same(n, o[0])), None)
                    if hit is not None:
                        o[1] = hit
                        used.add(hit)
    for (_, out), (_, src) in zip(rows, sets):
        for o, (_, seg) in zip(out, src):
            o[2] = seg
    return rows


def find_tape(date):
    for u in sorted(flb.uploads_for_date(date), key=flb.rank_key):
        ident = u['identifier']
        if flb.risky_source(ident):
            continue
        tracks = tape_tracks(ident)
        if tracks:
            return ident, tracks
    return None, []


def split_venue(v):
    parts = [p.strip() for p in v.split(',')]
    return (', '.join(parts[:-2]) or parts[0], ', '.join(parts[-2:])) if len(parts) >= 3 else (parts[0], ', '.join(parts[1:]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('archive')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    every = jerrybase.load(args.archive)
    jb = {d: s for d, s in every.items() if s['sets']}
    setlists = json.loads(SETLISTS.read_text())
    shows = flb.load_shows()
    have = {s['d'] for s in shows}
    stats, kept = {'updated': 0, 'kept_old': 0, 'added': 0, 'added_with_tape': 0}, []

    for date, entry in setlists.items():
        entry.setdefault('source', 'setlistprogram' if entry.get('full') else 'tape')
        s = jb.get(date)
        if not s:
            continue
        rows = apply_jb(jb_sets(s), entry.get('tracks') if entry.get('id') else [], entry.get('sets', []))
        n = sum(len(r) for _, r in rows)
        # Keep the old setlist when JerryBase's songs can't be found on the tape (unlabeled tracks, a tape of
        # another set, or a JerryBase setlist that only knows part of the show). Leaving out a New Riders or
        # Dylan set the old setlist mixed in is fine: JerryBase lists those as their own events.
        if entry.get('id') and matched(rows) < matched(entry.get('sets', [])) - 2 and matched(rows) < .8 * n:
            kept.append((date, matched(entry['sets']), matched(rows)))
            stats['kept_old'] += 1
            continue
        entry.update(sets=rows, full=True, source='jerrybase', jerrybase=s['jerrybase_urls'])
        stats['updated'] += 1

    new = sorted(d for d in every if d not in setlists and d not in have)
    with ThreadPoolExecutor(4) as pool:
        tapes = dict(zip(new, pool.map(find_tape, new)))
    for date in new:
        s, (ident, tracks) = every[date], tapes[date]
        if s['sets']:
            rows = apply_jb(jb_sets(s), tracks)
            if ident and matched(rows) < 2:  # a tape that doesn't hold this setlist is the wrong tape (or unlabeled)
                ident, tracks, rows = None, [], apply_jb(jb_sets(s), [])
            entry = {'sets': rows, 'full': True, 'source': 'jerrybase'}
        else:  # JerryBase knows the show happened but has no setlist: use the tape's track list, if any
            rows = tape_only(tracks) if ident else []
            entry = {'sets': rows, 'full': False, 'source': 'tape' if rows else 'none'}
        setlists[date] = {'id': ident, 'tracks': tracks, **entry, 'jerrybase': s['jerrybase_urls']}
        v, c = split_venue(s['venue'].split(' / ')[0])
        shows.append({'d': date, 'v': v, 'c': c, 'id': ident, 't': T[flb.source_class(ident)] if ident else None})
        stats['added'] += 1
        stats['added_with_tape'] += bool(ident)

    print(stats)
    if kept:
        print('Kept the old setlist (most of JerryBase\'s songs not found on the tape):', kept)
    if args.apply:
        shows.sort(key=lambda s: s['d'])
        flb.save_shows(shows)
        SETLISTS.write_text(json.dumps(dict(sorted(setlists.items())), ensure_ascii=False, separators=(',', ':')) + '\n')
        flb.bump_data_version('shows.json')
        print('Applied. Run tools/build_pages.py next.')
    else:
        print('Dry run. Re-run with --apply.')


if __name__ == '__main__':
    main()
