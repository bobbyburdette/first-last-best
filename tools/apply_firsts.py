"""Settle each song's First and Last against JerryBase, and make sure every First/Last card has a tape to play.

    python3 tools/apply_firsts.py ../first-last-best-archive            # dry run
    python3 tools/apply_firsts.py ../first-last-best-archive --apply

The documented date is the show the song was really first (or last) played at: JerryBase's date where the
review decided "accept", otherwise the site's current date. Review items still marked "look" are left alone.

If that show has a tape with the song, the card plays it. If not, the card plays the nearest show that does
(the earliest later one for First, the latest earlier one for Last) and keeps the documented show in
`documented`, which the site shows as an asterisk and a note. Cards whose date and tape don't change are
left exactly as they are (their tape choice may have been made by ear).

Decisions live in the archive repo: review/first-last-review.json (the items) and review/decisions.json
({item id: {"choice": "accept" | "keep" | "look"}}).
"""
import argparse
import json
from pathlib import Path

import flb
from fetch_setlists import OUT as SETLISTS, title_key

NO_TAPE = 'No tape survives.'


def source_of(pick):
    url = pick.get('source') or ''
    if 'jerrybase' in url:
        return 'JerryBase', url
    if 'dead.net' in url:
        return 'Dead.net', url
    if 'setlists.net' in url:
        return 'The SetList Program', url
    return pick.get('sourceLabel') or 'Source', url


def taped_dates(keys, setlists):
    """{date: (tape id, track)} for every show whose tape has the song."""
    out = {}
    for date, e in setlists.items():
        if not e.get('id'):
            continue
        for _, rows in e.get('sets', []):
            for title, idx, _ in rows:
                if idx >= 0 and title_key(title) in keys and idx < len(e['tracks']):
                    tr = e['tracks'][idx]
                    out.setdefault(date, ((e.get('tapes') or [e['id']])[tr[3] if len(tr) > 3 else 0], tr, e))
    return out


def pick_from_tape(date, tape, shows):
    ident, tr, e = tape
    s = shows.get(date) or {}
    src = (e.get('jerrybase') or [''])[0] if e.get('source') == 'jerrybase' else 'https://www.setlists.net/'
    return {'date': date, 'venue': f"{s.get('v', '')} - {s.get('c', '')}".strip(' -'), 'source': src, 'sourceLabel': 'Setlist',
            'audio': flb.audio_url(ident, tr[0]), 'track': tr[1], 'duration': tr[2],
            'combined': tr[1].rstrip().endswith('>'), 'identifier': ident,
            'recording': f'https://archive.org/details/{ident}', 'showId': f'gd-{date}'}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('archive')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    rev = Path(args.archive) / 'review'
    items = {i['id']: i for i in json.loads((rev / 'first-last-review.json').read_text())['items']}
    decisions = json.loads((rev / 'decisions.json').read_text())
    setlists = json.loads(SETLISTS.read_text())
    shows = {s['d']: s for s in flb.load_shows()}
    songs = flb.load_songs()
    changed = []
    for song in songs:
        if song.get('kind') == 'sequence':
            continue
        keys = {title_key(n) for n in flb.song_names(song)}
        taped = taped_dates(keys, setlists)
        for slot in ('first', 'last'):
            cur = song.get(slot) or {}
            if not cur.get('date'):
                continue
            item = items.get(f"{flb.norm_title(song['name'])}-{slot}")
            choice = (decisions.get(item['id']) or {}).get('choice') if item else None
            if item and choice in (None, 'look'):
                continue  # waiting on a person
            old_doc = cur.get('documented') or {}
            if choice == 'accept':
                label, url = 'JerryBase', item['jb']['url']
                doc = {'date': item['jb']['date'], 'venue': item['jb']['venue'], 'source': label, 'url': url}
            elif old_doc:
                doc = dict(old_doc)
            else:
                label, url = source_of(cur)
                doc = {'date': cur['date'], 'venue': cur.get('venue', '').replace(' - ', ', '), 'source': label, 'url': url}
            d = doc['date']
            if d in taped or (cur.get('date') == d and cur.get('audio')):
                new = cur if cur.get('date') == d and cur.get('audio') else pick_from_tape(d, taped[d], shows)
                new = {k: v for k, v in new.items() if k != 'documented'}
            else:
                near = sorted(x for x in taped if (x > d if slot == 'first' else x < d))
                if not near:
                    continue  # no tape of the song anywhere: leave the card as it is
                t = near[0] if slot == 'first' else near[-1]
                new = {k: v for k, v in cur.items() if k != 'documented'} if cur.get('date') == t and cur.get('audio') \
                    else pick_from_tape(t, taped[t], shows)
                note = old_doc.get('note') or ' '.join(x for x in (NO_TAPE, cur.get('note') if not cur.get('audio') else '') if x)
                new['documented'] = {**doc, 'note': note, **({'kicker': old_doc['kicker']} if old_doc.get('kicker') else {})}
            if new != cur:
                song[slot] = new
                changed.append((song['name'], slot, cur.get('date'), new['date'], (new.get('documented') or {}).get('date')))
    for c in changed:
        print(f'{c[0]} {c[1]}: card {c[2]} -> {c[3]}' + (f' (note: really {c[4]})' if c[4] else ''))
    print(f'{len(changed)} cards change.')
    if args.apply:
        flb.save_songs(songs)
        flb.bump_data_version('songs.json')
        print('Applied. Run tools/build_pages.py next.')
    else:
        print('Dry run. Re-run with --apply.')


if __name__ == '__main__':
    main()
