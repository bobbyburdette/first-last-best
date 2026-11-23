"""Play the best tape of every show: the upload listeners rate highest, not just the best recording type.

    python3 tools/best_tapes.py                      # dry run: writes the before/after plan, changes nothing
    python3 tools/best_tapes.py --apply              # switch shows, setlists and First/Last/Best picks
    python3 tools/best_tapes.py --report PATH.json   # where to write the plan (default: tools/.cache/best_tapes.json)

Each archive.org upload of a date gets a score:
  - its listener rating, weighted by how many people rated it (a 4.4 from 19 reviews beats a 5.0 from one):
    (avg * reviews + 3.8 * 4) / (reviews + 4), so an unrated tape counts as an ordinary 3.8;
  - small nudges: soundboard or matrix +0.15, unlabeled -0.1, a Charlie Miller transfer or a Betty Board +0.1,
    and popularity (downloads) up to about +0.2.
A show moves to the top scorer only when it beats the current tape by at least 0.15 and its tracks match the
setlist at least as well as the current tape's. A First/Last/Best pick moves when the new tape has the song as a
labeled track within 30% of the current length. Anything else that looks better is listed for a person to hear.
Monitor mixes and half-aud/half-sbd uploads are never picked; shows played from two tapes are left alone.
"""
import argparse
import json
import math
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import flb
from fetch_setlists import OUT as SETLISTS, tape_tracks
from merge_jerrybase import apply_jb, matched

MARGIN = 0.15
TYPE = {flb.SBD: 'sbd', flb.MATRIX: 'mtx', flb.AUD: 'aud', flb.UNKNOWN: 'unk'}


def uploads(date):
    q = urllib.parse.quote(f'collection:GratefulDead AND date:{date}')
    url = (f'https://archive.org/advancedsearch.php?q={q}&fl[]=identifier&fl[]=avg_rating&fl[]=num_reviews'
           f'&fl[]=downloads&rows=100&output=json')
    try:
        return flb._cached_json('uploads-scored', date, url)['response']['docs']
    except Exception:
        return []


def score(u):
    ident = u['identifier']
    n = float(u.get('num_reviews') or 0)
    avg = float(u.get('avg_rating') or 0) if n else 0
    s = (avg * n + 3.8 * 4) / (n + 4)
    c = flb.source_class(ident)
    s += {flb.SBD: .15, flb.MATRIX: .15, flb.AUD: 0, flb.UNKNOWN: -.1}[c]
    if flb.is_miller(ident) or 'betty' in ident.lower():
        s += .1
    s += min(.2, math.log10(1 + float(u.get('downloads') or 0)) * .04)
    return round(s, 3)


def ranked(date):
    us = [u for u in uploads(date) if not flb.risky_source(u['identifier'])]
    return sorted(((score(u), u) for u in us), key=lambda x: -x[0])


def info(u):
    return {'id': u['identifier'], 'type': TYPE[flb.source_class(u['identifier'])],
            'rating': u.get('avg_rating'), 'reviews': u.get('num_reviews') or 0, 'downloads': u.get('downloads') or 0}


def plan_show(show, entry):
    """(new tape doc, new setlist entry or None, why-not) for one show."""
    cur = show['id']
    ranks = ranked(show['d'])
    if not ranks:
        return None
    scores = {u['identifier']: s for s, u in ranks}
    cur_s = scores.get(cur, 0)
    for s, u in ranks[:4]:
        new = u['identifier']
        if new == cur:
            return None  # the current tape is already the best scorer we can use
        if s < cur_s + MARGIN:
            return {'show': show['d'], 'held': 'close call', 'cur': cur, 'cur_score': cur_s, 'new': info(u), 'new_score': s}
        tracks = tape_tracks(new)
        if not tracks:
            continue  # no streamable MP3s: try the next one
        if entry and entry.get('sets') and not entry.get('tapes'):
            sets = [(l, [[r[0], r[2]] for r in rows]) for l, rows in entry['sets']]
            rows = apply_jb(sets, tracks)
            old = matched(entry['sets']) if entry.get('id') else 0
            if matched(rows) < old:
                return {'show': show['d'], 'held': f'tracks line up worse ({matched(rows)} vs {old} songs)',
                        'cur': cur, 'cur_score': cur_s, 'new': info(u), 'new_score': s}
            return {'show': show['d'], 'cur': cur, 'cur_score': cur_s, 'new': info(u), 'new_score': s,
                    'tracks': tracks, 'sets': rows, 'matched': [old, matched(rows)]}
        if entry and entry.get('tapes'):
            return None
        return {'show': show['d'], 'cur': cur, 'cur_score': cur_s, 'new': info(u), 'new_score': s, 'tracks': tracks}
    return None


def plan_picks(songs, tape_for):
    """Move First/Last/Best picks (and Best runners-up) to the best tape of their date."""
    swaps, held = [], []
    for song in songs:
        if song.get('kind') == 'sequence':
            continue
        for slot, pick in flb.picks(song):
            cur, d = pick.get('identifier'), pick.get('date')
            if not (cur and d and pick.get('audio')) or pick.get('locked'):
                continue
            ranks = ranked(d)
            scores = {u['identifier']: s for s, u in ranks}
            want = tape_for.get(d) or (ranks[0][1]['identifier'] if ranks else None)
            if not want or want == cur or scores.get(want, 0) < scores.get(cur, 0) + MARGIN:
                continue
            try:
                track = flb.find_track(want, flb.song_names(song))
            except Exception:
                track = None
            row = {'song': song['name'], 'slot': slot, 'date': d, 'cur': cur, 'new': want,
                   'cur_score': scores.get(cur, 0), 'new_score': scores.get(want, 0)}
            if not track:
                held.append({**row, 'held': 'song not labeled on the better tape'})
                continue
            cd, nd = flb.secs(pick.get('duration', '0')), flb.secs(track['length'])
            if cd and abs(nd - cd) / cd > .30:
                held.append({**row, 'held': f"length {pick.get('duration')} vs {track['length']}"})
                continue
            swaps.append({**row, 'track': track})
    return swaps, held


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--report', default=str(flb.CACHE / 'best_tapes.json'))
    args = ap.parse_args()
    shows = flb.load_shows()
    setlists = json.loads(SETLISTS.read_text())
    todo = [s for s in shows if s.get('id') and not s.get('x')]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda s: uploads(s['d']), todo))  # warm the cache
        plans = list(pool.map(lambda s: plan_show(s, setlists.get(s['d'])), todo))
    show_swaps = [p for p in plans if p and 'held' not in p]
    show_held = [p for p in plans if p and 'held' in p]
    tape_for = {p['show']: p['new']['id'] for p in show_swaps}
    tape_for.update({s['d']: s['id'] for s in todo if s['d'] not in tape_for})
    songs = flb.load_songs()
    pick_swaps, pick_held = plan_picks(songs, tape_for)

    report = {'shows': [{k: v for k, v in p.items() if k not in ('tracks', 'sets')} for p in show_swaps],
              'shows_held': show_held, 'picks': [{k: v for k, v in p.items() if k != 'track'} for p in pick_swaps],
              'picks_held': pick_held}
    with open(args.report, 'w') as f:
        json.dump(report, f, indent=1)
    print(f'{len(show_swaps)} shows switch, {len(show_held)} held for a listen; '
          f'{len(pick_swaps)} picks switch, {len(pick_held)} held. Plan: {args.report}')
    if not args.apply:
        print('Dry run. Re-run with --apply.')
        return

    by_date = {s['d']: s for s in shows}
    for p in show_swaps:
        s, new = by_date[p['show']], p['new']['id']
        s['id'], s['t'] = new, TYPE[flb.source_class(new)]
        e = setlists.get(p['show'])
        if e is not None:
            e['id'], e['tracks'] = new, p['tracks']
            if 'sets' in p:
                e['sets'] = p['sets']
    by_name = {s['name']: s for s in songs}
    for p in pick_swaps:
        pick = dict(flb.picks(by_name[p['song']]))[p['slot']]
        t = p['track']
        pick.update(audio=flb.audio_url(p['new'], t['name']), track=t['title'], duration=t['length'],
                    identifier=p['new'], recording=f"https://archive.org/details/{p['new']}",
                    combined=t['title'].rstrip().endswith('>'))
        pick.pop('rating', None)
        pick.pop('reviews', None)
    flb.save_shows(shows)
    SETLISTS.write_text(json.dumps(dict(sorted(setlists.items())), ensure_ascii=False, separators=(',', ':')) + '\n')
    flb.save_songs(songs)
    flb.bump_data_version('shows.json')
    flb.bump_data_version('songs.json')
    print('Applied. Run tools/build_tapes.py, tools/check_audio.py and tools/build_pages.py next.')


if __name__ == '__main__':
    main()
