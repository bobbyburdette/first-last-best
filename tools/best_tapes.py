"""Play the best tape of every show: the upload listeners rate highest, not just the best recording type.

    python3 tools/best_tapes.py                      # dry run: writes the before/after plan, changes nothing
    python3 tools/best_tapes.py --apply              # switch shows, setlists and First/Last/Best picks
    python3 tools/best_tapes.py --report PATH.json   # where to write the plan (default: tools/.cache/best_tapes.json)

Each archive.org upload of a date gets a score:
  - its listener rating, weighted by how many people rated it (a 4.4 from 19 reviews beats a 5.0 from one):
    (avg * reviews + 3.8 * 4) / (reviews + 4), so an unrated tape counts as an ordinary 3.8;
  - small nudges: soundboard or matrix +0.15, unlabeled -0.1, a Charlie Miller transfer or a Betty Board +0.1,
    and popularity (downloads) up to about +0.2.
A show with a setlist is assembled song by song: each song plays from the best-scoring tape that has it (up to
three tapes; a tape after the first must add at least two songs), so a great partial tape is used for the songs
it has and another tape fills the rest. The tape playing the most songs is the show's main tape. A show changes
only when it keeps every song it could already play and gets better by at least 0.15 per song on average (or
can play more songs without getting worse). A tape the search doesn't list is scored from its own reviews.
A First/Last/Best pick moves to the tape that plays its song in the show, when that tape scores at least 0.15
higher and has the song as a labeled track within 30% of the current length (never a locked pick or a Longest
card, which was chosen for its length on that exact tape). Monitor mixes and half-aud/half-sbd uploads are never
picked; a show without a tape doesn't get one here.
"""
import argparse
import json
import math
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import flb
from fetch_setlists import OUT as SETLISTS, tape_label, tape_tracks, title_key
from merge_jerrybase import apply_jb, matched

MARGIN = 0.15
TYPE = {flb.SBD: 'sbd', flb.MATRIX: 'mtx', flb.AUD: 'aud', flb.UNKNOWN: 'unk'}


def uploads(date):
    q = urllib.parse.quote(f'collection:GratefulDead AND date:{date}')
    url = (f'https://archive.org/advancedsearch.php?q={q}&fl[]=identifier&fl[]=avg_rating&fl[]=num_reviews'
           f'&fl[]=downloads&fl[]=taper&fl[]=transferer&fl[]=source&rows=100&output=json')
    try:
        return flb._cached_json('uploads-full', date, url)['response']['docs']
    except Exception:
        return []


def id_date(ident):
    """The date in an upload's name (gd1983-04-10..., gd83-04-10...), or None when it has none."""
    m = re.match(r'gd(?:_\w+?)?(\d{2}|\d{4})-(\d\d)-(\d\d)', ident.lower())
    if not m:
        return None
    y = m.group(1)
    return f"{'19' + y if len(y) == 2 else y}-{m.group(2)}-{m.group(3)}"


def right_day(ident, date):
    d = id_date(ident)
    return d is None or d == date


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
    us = [u for u in uploads(date) if not flb.risky_source(u['identifier']) and right_day(u['identifier'], date)]
    return sorted(((score(u), u) for u in us), key=lambda x: -x[0])


def doc_for(ident, date):
    """An upload's search entry, or one built from its own reviews when the search doesn't list it."""
    for u in uploads(date):
        if u['identifier'] == ident:
            return u
    try:
        m = flb.metadata(ident)
    except Exception:
        m = {}
    stars = [float(r['stars']) for r in m.get('reviews', []) if str(r.get('stars', '')).replace('.', '', 1).isdigit()]
    return {'identifier': ident, 'avg_rating': sum(stars) / len(stars) if stars else None, 'num_reviews': len(stars),
            'downloads': (m.get('item') or {}).get('downloads', 0)}


def tape_score(ident, date):
    return score(doc_for(ident, date)) if right_day(ident, date) else -1.0


def info(u):
    return {'id': u['identifier'], 'type': TYPE[flb.source_class(u['identifier'])],
            'rating': u.get('avg_rating'), 'reviews': u.get('num_reviews') or 0, 'downloads': u.get('downloads') or 0}


def fill_gaps(rows, tracks):
    """A song the matcher missed (the taper titled it differently, e.g. 'Women are Smarter') takes the one unused
    track between its matched neighbors."""
    flat = [r for _, rs in rows for r in rs]
    used = {r[1] for r in flat if r[1] >= 0}
    for i, r in enumerate(flat):
        if r[1] >= 0 or not 0 < i < len(flat) - 1:
            continue
        a, b = flat[i - 1][1], flat[i + 1][1]
        if a >= 0 and b == a + 2 and a + 1 not in used and a + 1 < len(tracks):
            r[1] = a + 1
            used.add(a + 1)
    return rows


def current_tapes(entry):
    return entry.get('tapes') or ([entry['id']] if entry.get('id') else [])


def song_tapes(entry):
    """[(row, tape id or None)] for every song in a setlist entry."""
    ids = current_tapes(entry)
    out = []
    for _, rows in entry.get('sets', []):
        for r in rows:
            k = (entry['tracks'][r[1]][3] if len(entry['tracks'][r[1]]) > 3 else 0) if r[1] >= 0 else None
            out.append((r, ids[k] if k is not None and ids else None))
    return out


def plan_single(show):
    """A show with no setlist: just its main tape."""
    cur, d = show['id'], show['d']
    ranks = ranked(d)
    cur_s = tape_score(cur, d)
    for s, u in ranks[:4]:
        if u['identifier'] == cur or s < cur_s + MARGIN:
            return None
        tracks = tape_tracks(u['identifier'])
        if tracks:
            return {'show': d, 'cur': [cur], 'new': [u['identifier']], 'gain': round(s - cur_s, 2),
                    'scores': {cur: cur_s, u['identifier']: s}, 'tracks': tracks}
    return None


def plan_show(show, entry):
    """Assemble the show from the best tape for each song; None when nothing should change."""
    d = show['d']
    if not entry or not entry.get('sets') or not entry.get('id'):
        return plan_single(show) if show.get('id') and not entry else None
    sets = [(l, [[r[0], r[2]] for r in rows]) for l, rows in entry['sets']]
    n = sum(len(rs) for _, rs in sets)
    cur_ids = current_tapes(entry)
    cands = {u['identifier']: s for s, u in ranked(d)[:6]}
    for i in cur_ids:
        cands.setdefault(i, tape_score(i, d))
    assign, used = {}, []  # song position -> (tape slot, track)
    for ident, s in sorted(cands.items(), key=lambda x: -x[1]):
        if len(used) >= 3 or len(assign) == n:
            break
        tracks = tape_tracks(ident)
        if not tracks:
            continue
        flat = [r for _, rs in fill_gaps(apply_jb(sets, tracks), tracks) for r in rs]
        new = [i for i, r in enumerate(flat) if r[1] >= 0 and i not in assign]
        if len(new) < min(2, n) or not new:
            continue
        used.append([ident, s, tracks])
        for i in new:
            assign[i] = (len(used) - 1, flat[i][1])
    if not used:
        return None
    count = [sum(1 for k, _ in assign.values() if k == j) for j in range(len(used))]
    order = sorted(range(len(used)), key=lambda j: (-count[j], -used[j][1]))
    slot = {j: k for k, j in enumerate(order)}
    tapes = [used[j] for j in order]
    offsets, tracks = [], []
    for k, (_, _, tt) in enumerate(tapes):
        offsets.append(len(tracks))
        tracks += [list(x[:3]) + ([k] if k else []) for x in tt]
    rows, pos = [], 0
    for label, rs in sets:
        out = []
        for name, seg in rs:
            a = assign.get(pos)
            out.append([name, offsets[slot[a[0]]] + a[1] if a else -1, seg])
            pos += 1
        rows.append([label, out])
    ids = [x[0] for x in tapes]
    scores = {**{i: cands.get(i, tape_score(i, d)) for i in cur_ids}, **{x[0]: x[1] for x in tapes}}
    cur_rows = song_tapes(entry)
    cur_m = sum(1 for r, _ in cur_rows if r[1] >= 0)
    cur_q = sum(scores[i] for r, i in cur_rows if r[1] >= 0 and i)
    new_q = sum(tapes[slot[k]][1] for k, _ in assign.values())
    if ids == cur_ids and [r[1] for _, rs in rows for r in rs] == [r[1] for r, _ in cur_rows]:
        return None
    gain = (new_q - cur_q) / n
    if len(assign) < cur_m or not (gain >= MARGIN or (len(assign) > cur_m and new_q >= cur_q)):
        return None
    return {'show': d, 'cur': cur_ids, 'new': ids, 'gain': round(gain, 2), 'matched': [cur_m, len(assign)],
            'songs_per_tape': [count[j] for j in order], 'scores': scores, 'tracks': tracks, 'sets': rows}


def plan_picks(songs, setlists, shows):
    """Move First/Last/Best picks (and Best runners-up) to the tape that plays their song in the show."""
    swaps, held = [], []
    for song in songs:
        if song.get('kind') == 'sequence':
            continue
        for slot, pick in flb.picks(song):
            cur, d = pick.get('identifier'), pick.get('date')
            if not (cur and d and pick.get('audio')) or pick.get('locked') or pick.get('sourceType') == 'longest':
                continue  # locked: set by hand; Longest: chosen for its length on that exact tape
            keys = {title_key(x) for x in flb.song_names(song)}
            e = setlists.get(d) or {}
            want = next((i for r, i in song_tapes(e) if i and r[1] >= 0 and title_key(r[0]) in keys), None) \
                if e.get('sets') and e.get('id') else (shows.get(d) or {}).get('id')
            if not want or want == cur:
                continue
            scores = {cur: tape_score(cur, d), want: tape_score(want, d)}
            if scores[want] < scores[cur] + MARGIN:
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


ALT = flb.ROOT / 'data' / 'alt_tapes.json'


def text(v):
    v = ' '.join(v) if isinstance(v, list) else str(v or '')
    v = re.sub(r'<[^>]+>', ' ', v)
    return re.sub(r'\s+', ' ', ''.join(c for c in v if c.isascii() and c.isprintable())).strip()


def label(u):
    """Who made the tape, as briefly as the upload says: 'Taped by X', 'Transfer by X', or its source chain."""
    taper, xfer, src = text(u.get('taper')), text(u.get('transferer')), text(u.get('source'))
    if taper and not re.match(r'(?i)unknown|n/?a$', taper):
        return 'Taped by ' + re.split(r'[:;,(]', taper)[0].strip()[:40]
    if xfer and not re.match(r'(?i)unknown|n/?a$', xfer):
        x = re.split(r'[;,(]', xfer)[0].strip()[:40]
        return x if re.search(r'\d', x) else 'Transfer by ' + x
    src = re.sub(r'(?i)^(set|disc|cd)\s*\d+\s*[:-]?\s*', '', re.split(r'[;>]|-->', src)[0]).strip()
    src = re.sub(r'^KG (?=\d)', 'AKG ', src)  # a mangled 'AKG' in some old uploads
    if len(re.sub(r'(?i)\b(sbd|aud|soundboard|audience|matrix|mtx|master|unknown|source|dat|cdr?|pcm|reel)\b|\W', '', src)) < 3:
        who = [w for w in re.split(r'[._-]', u['identifier'].lower())[1:] if w.isalpha() and len(w) > 3
               and w not in STOP]
        return ('via ' + who[0].title()) if who else ''
    return src[:40]


STOP = {'sbeok', 'shnf', 'flac', 'flacf', 'late', 'early', 'show', 'partial', 'remaster', 'master', 'soundboard', 'audience',
        'matrix', 'fixed', 'retracked', 'sbefail', 'unknown', 'unkn', 'betty', 'board', 'blend', 'patch', 'shure', 'senn',
        'schoeps', 'neumann', 'akgck', 'nakcm', 'sony', 'binaural', 'stereo', 'mono', 'digital', 'analog', 'composite'}


def alt_tapes(date, current):
    """Every tape of a show for the tape switcher: [[id, type, rating, reviews, label, versions, partial], ...],
    the site's pick first, then by score; uploads of one recording (same taper or source) are grouped."""
    groups = {}
    ranks = ranked(date)
    if current not in {u['identifier'] for _, u in ranks}:
        ranks.append((tape_score(current, date), doc_for(current, date)))
    for s, u in ranks:
        lab = label(u)
        key = (flb.source_class(u['identifier']), re.sub(r'[^a-z0-9]', '', lab.lower())[:30] or u['identifier'])
        g = groups.setdefault(key, [s, u, lab, 0])
        g[3] += 1
        if u['identifier'] == current:
            g[0], g[1] = 99, u  # the site's pick represents its group
    rows = sorted(groups.values(), key=lambda g: -g[0])
    out = [[u['identifier'], TYPE[flb.source_class(u['identifier'])], round(float(u.get('avg_rating') or 0), 2),
            int(u.get('num_reviews') or 0), lab, n, int(bool(re.search(r'(?i)(^|[._-])(s|set)\d([._-]|$)|partial', u['identifier'])))]
           for _, u, lab, n in rows]
    return out if len(out) > 1 and out[0][0] == current else None


def write_alt(shows):
    todo = [s for s in shows if s.get('id') and not s.get('x')]
    with ThreadPoolExecutor(8) as pool:
        lists = list(pool.map(lambda s: alt_tapes(s['d'], s['id']), todo))
    data = {s['d']: l for s, l in zip(todo, lists) if l}
    ALT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'Tape switcher: {len(data)} shows with more than one tape -> {ALT.name}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--report', default=str(flb.CACHE / 'best_tapes.json'))
    ap.add_argument('--alt', action='store_true', help='only rewrite data/alt_tapes.json (the tape switcher lists)')
    args = ap.parse_args()
    if args.alt:
        write_alt(flb.load_shows())
        return
    shows = flb.load_shows()
    setlists = json.loads(SETLISTS.read_text())
    todo = [s for s in shows if s.get('id') and not s.get('x') and not s.get('xs')]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda s: uploads(s['d']), todo))  # warm the cache
        plans = [p for p in pool.map(lambda s: plan_show(s, setlists.get(s['d'])), todo) if p]
    by_date = {s['d']: s for s in shows}
    for p in plans:
        s, main_id = by_date[p['show']], p['new'][0]
        s['id'], s['t'] = main_id, TYPE[flb.source_class(main_id)]
        e = setlists.get(p['show'])
        if e is not None and 'sets' in p:
            e.update(id=main_id, tracks=p['tracks'], sets=p['sets'])
            if len(p['new']) > 1:
                e['tapes'], e['kinds'] = p['new'], [tape_label(i) for i in p['new']]
            else:
                e.pop('tapes', None)
                e.pop('kinds', None)
        elif e is not None:
            e.update(id=main_id, tracks=p['tracks'])
    songs = flb.load_songs()
    pick_swaps, pick_held = plan_picks(songs, setlists, by_date)
    report = {'shows': [{k: v for k, v in p.items() if k not in ('tracks', 'sets')} for p in plans],
              'picks': [{k: v for k, v in p.items() if k != 'track'} for p in pick_swaps], 'picks_held': pick_held}
    with open(args.report, 'w') as f:
        json.dump(report, f, indent=1)
    multi = sum(1 for p in plans if len(p['new']) > 1)
    print(f'{len(plans)} shows change ({multi} play from more than one tape); '
          f'{len(pick_swaps)} picks move, {len(pick_held)} held. Plan: {args.report}')
    if not args.apply:
        print('Dry run. Re-run with --apply.')
        return
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
    write_alt(shows)
    print('Applied. Run tools/build_tapes.py, tools/check_audio.py and tools/build_pages.py next.')


if __name__ == '__main__':
    main()
