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
three tapes; a backup tape may fill even a single missing song), so a great partial tape is used for the songs
it has and another tape fills the rest. The tape playing the most songs is the show's main tape. A show changes
only when it keeps every song it could already play and gets better by at least 0.15 per song on average (or
can play more songs without getting worse). A tape the search doesn't list is scored from its own reviews.
A First/Last/Best pick moves to the tape that plays its song in the show, when that tape scores at least 0.15
higher and has the song as a labeled track within 30% of the current length (never a locked pick or a Longest
card, which was chosen for its length on that exact tape). Monitor mixes and half-aud/half-sbd uploads are never
picked; a show without a tape doesn't get one here.
"""
import argparse
import functools
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


# What listeners say in their reviews, read with a short phrase list (no guessing at tone): each flag is
# (note shown in the tape switcher, phrase, weight). A sentence that mentions a fix or another tape ("the speed
# was corrected", "unlike the old source") or plays the problem down ("no hiss", "minor dropouts") doesn't count.
FLAGS = [
    ('runs fast', r'\b(runs?|plays?|running|too|bit|little|slightly|way)\s+(a\s+bit\s+|too\s+)?fast\b|\bsped up\b'
                  r'|\bpitch(ed)?\s+(is\s+)?(too\s+)?(high|sharp)\b', .3),
    ('runs slow', r'\b(runs?|plays?|running|too|bit|little|slightly|way)\s+(a\s+bit\s+|too\s+)?slow\b'
                  r'|\bpitch(ed)?\s+(is\s+)?(too\s+)?(low|flat)\b', .3),
    ('speed problems', r'\b(speed|pitch)\s+(is\s+|was\s+)?(off|wrong|issues?|problems?|fluctuat\w*|wobbl\w*|varies|drifts?)\b'
                       r'|\bwow\s+(and|&)\s+flutter\b|\bwarbl\w*', .3),
    ('hiss', r'\b(lots of|heavy|loud|excessive|bad|too much|annoying|very)\s+(tape\s+)?hiss\w*', .15),
    ('dropouts', r'\bdrop-?\s?outs?\b', .15),
    ('distortion', r'\b(sound|recording|tape|source|audio|levels?|vocals?|bass|mix|transfer)\s+(is\s+|was\s+|gets?\s+|a\s+bit\s+|very\s+|quite\s+|pretty\s+)*distort\w*'
                   r'|\bdistortion\s+(on|in|throughout|problems?|issues?)\b|\bclipp(ing|ed)\b|\boverload\w*', .15),
    ('muddy sound', r'\b(sound|recording|tape|source|audio|mix|transfer)s?\s+(is\s+|was\s+|are\s+|a\s+bit\s+|rather\s+|pretty\s+|very\s+|quite\s+|kind\s+of\s+|somewhat\s+)*(muddy|muffled|tinny|boomy|murky)\b'
                    r'|\b(muddy|muffled|tinny|boomy|murky)\s+(sound\w*|mix|recording|tape|audio|source|transfer)\b', .15),
    ('cuts', r'\bcuts?\s+(out|off)\b|\babrupt(ly)?\s+(cut|end)|\bmissing\s+(songs?|tracks?|parts?)\b', .1),
    ('glitches', r'\bglitch\w*|\bdigital\s+(noise|errors?|clicks?)\b', .1),
]
GOOD = (r'\bbest[- ]sounding\b|\bbest\s+(source|version|recording|copy|transfer|tape|sbd|soundboard|quality|sound)\b'
        r'|\bsounds?\s+(amazing|incredible|fantastic|excellent|stellar|pristine|perfect|superb)\b|\bcrystal\s*clear\b'
        r'|\bpristine\b|\bimpeccable\b|\b(huge|big|major|massive)\s+upgrade\b')
EXCUSE = (r'\b(fix|fixe[sd]|correct(ed|s|ion)?|re-?pitch\w*|adjust\w*|resolved|repaired|no longer|unlike|other\s+(source|version|tape|copy)s?'
          r'|previous|older|old\s+(source|version|transfer|copy)|no|not|without|free of|zero|minimal|minor|slight|slightly|barely|hardly'
          r'|little|tiny|occasional|few)\b')


def reviews(ident):
    """An upload's archive.org reviews: from its cached metadata, else just the reviews (a small request)."""
    path = flb.CACHE / 'meta' / (re.sub(r'[^A-Za-z0-9._-]', '_', ident) + '.json')
    if path.exists():
        return json.loads(path.read_text()).get('reviews') or []
    try:
        return flb._cached_json('reviews', ident, f'https://archive.org/metadata/{ident}/reviews').get('result') or []
    except Exception:
        return []


@functools.lru_cache(maxsize=None)
def comments(ident):
    """(score nudge, switcher note) from what reviewers say. A problem counts once two reviewers mention it; it
    shows in the switcher when it's also at least 1 in 10 of the reviews. Praise ('best sounding') nudges up."""
    rv = [' '.join(str(r.get(k) or '') for k in ('reviewtitle', 'reviewbody')) for r in reviews(ident)]
    rv = [t for t in rv if t.strip()]
    if len(rv) < 2:
        return 0.0, ''
    hits, good = {}, 0
    for t in rv:
        found = set()
        for sent in re.split(r'(?<=[.!?;])\s+|\n+', re.sub(r'black\s+muddy(\s+river)?', 'bmr', t.lower())):  # the song
            if re.search(EXCUSE, sent):
                continue
            found |= {note for note, pat, _ in FLAGS if re.search(pat, sent)}
        for note in found:
            hits[note] = hits.get(note, 0) + 1
        good += bool(re.search(GOOD, t.lower()))
    w = {note: wt for note, _, wt in FLAGS}
    bad = sum(w[k] * c / len(rv) for k, c in hits.items() if c >= 2)
    nudge = -min(.3, 2.5 * bad) + (min(.15, .3 * good / len(rv)) if good >= 2 else 0)
    notes = sorted((k for k, c in hits.items() if c >= 2 and c / len(rv) >= .1), key=lambda k: -w[k] * hits[k])
    return round(nudge, 3), ', '.join(notes[:2])


def score(u):
    """Listener rating weighted toward tapes many people rated (the crowd favorite), with a soundboard bonus like
    Relisten's soundboard-first order, small nudges for Miller transfers, Betty Boards and downloads, and what
    reviewers say about the sound."""
    ident = u['identifier']
    n = float(u.get('num_reviews') or 0)
    avg = float(u.get('avg_rating') or 0) if n else 0
    s = (avg * n + 3.9 * 10) / (n + 10) + .12 * math.log10(1 + n)
    c = flb.source_class(ident)
    s += {flb.SBD: .2, flb.MATRIX: .12, flb.AUD: 0, flb.UNKNOWN: -.1}[c]
    if flb.is_miller(ident) or 'betty' in ident.lower():
        s += .1
    s += min(.2, math.log10(1 + float(u.get('downloads') or 0)) * .04)
    s += comments(ident)[0] if n >= 2 else 0
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
    for i in range(1, len(flat)):  # 'Scarlet Begonias -> Fire On The Mountain' as one track: Fire is in it
        r, prev = flat[i], flat[i - 1]
        if r[1] < 0 and 0 <= prev[1] < len(tracks) and title_key(prev[0]) in title_key(tracks[prev[1]][1]) \
                and holds(tracks[prev[1]], prev[0], r[0]):
            r[1] = prev[1]
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


def secs(t):
    try:
        return flb.secs(t[2]) if len(t) > 2 and t[2] else 0
    except Exception:
        return 0


def holds(track, prev_name, name, other=None):
    """Whether a combined track ('Scarlet Begonias -> Fire On The Mountain') holds `name`, the song after
    `prev_name`. Against another tape's separate track of the song it must be clearly longer, or the same length
    (the same audio uploaded twice); a short 'Drums -> The Other One' doesn't hold a 16-minute Other One."""
    k, t = title_key(name), title_key(track[1])
    if not (len(k) > 3 and k in t and k != title_key(prev_name)):
        return False
    if other is None:
        return True
    la, lb = secs(track), secs(other)
    return not la or not lb or abs(la - lb) <= 2 or la >= 1.2 * lb


def doubles(entry, fix=False):
    """Songs the show plays twice: a backup tape's song that the track before it already holds
    ('China Cat Sunflower > I Know You Rider', then 'I Know You Rider' again from another tape). With fix, the
    song points at the track that holds it, so it plays once."""
    if not entry.get('tapes') or not entry.get('sets'):
        return 0
    flat, tr, n = [r for _, rs in entry['sets'] for r in rs], entry['tracks'], 0
    tape = lambda i: tr[i][3] if len(tr[i]) > 3 else 0
    for a, b in zip(flat, flat[1:]):
        if a[1] >= 0 and b[1] >= 0 and tape(a[1]) != tape(b[1]) and holds(tr[a[1]], a[0], b[0], tr[b[1]]):
            n += 1
            if fix:
                b[1] = a[1]
    return n


def fix_doubles(entry):
    return doubles(entry, fix=True)


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
        if not new or (not used and len(new) < min(2, n)):
            continue  # a backup tape may fill even one song: a song from another tape beats a song you can't play
        used.append([ident, s, tracks, flat])
        for i in new:
            assign[i] = (len(used) - 1, flat[i][1])
    if not used:
        return None
    for i in sorted(assign):
        j, t = assign[i]
        if i == 0 or assign.get(i - 1) != (j, t):
            continue  # not held by the track before it
        for j2, (_, _, tt, fl) in enumerate(used):
            t2 = fl[i][1]
            if j2 != j and t2 >= 0 and t2 != fl[i - 1][1] and not holds(used[j][2][t], fl[i - 1][0], fl[i][0], tt[t2]):
                assign[i] = (j2, t2)  # the other tape has the song as its own, fuller track
                break
    # A fragment (a tape cut: 'Bertha' at 0:40) gives way to another tape's song track more than twice as long.
    pool = {u[0]: u for u in used}

    def tape(ident):
        if ident not in pool:
            tt = tape_tracks(ident) or []
            pool[ident] = [ident, cands[ident], tt, [r for _, rs in fill_gaps(apply_jb(sets, tt), tt) for r in rs] if tt else []]
        return pool[ident]

    def own(fl, i):  # the song's own track on a tape (a combined track shared with a neighbor can't be compared)
        t = fl[i][1] if fl else -1
        return t if t >= 0 and all(not 0 <= x < len(fl) or fl[x][1] != t for x in (i - 1, i + 1)) else -1

    cut = set()
    for i in sorted(assign):
        j, t = assign[i]
        la = secs(used[j][2][t]) if own(used[j][3], i) >= 0 else 0
        if not la:
            continue
        for ident in sorted(cands, key=lambda x: -cands[x]):
            if ident == used[j][0]:
                continue
            u = tape(ident)
            t2 = own(u[3], i)
            lb = secs(u[2][t2]) if t2 >= 0 else 0
            if not (lb >= 120 and ((la < 150 and la < .4 * lb) or la < .25 * lb)):  # a real cut, not tuning time
                continue
            ids_used = [x[0] for x in used]
            if ident not in ids_used:
                if len(used) >= 3:
                    continue
                used.append(u)
                ids_used.append(ident)
            assign[i] = (ids_used.index(ident), t2)
            cut.add(i)
            break
    count = [sum(1 for k, _ in assign.values() if k == j) for j in range(len(used))]
    order = [j for j in sorted(range(len(used)), key=lambda j: (-count[j], -used[j][1])) if count[j]]
    slot = {j: k for k, j in enumerate(order)}
    tapes = [used[j] for j in order]
    offsets, tracks = [], []
    for k, (_, _, tt, _) in enumerate(tapes):
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
    cur_flat = [r for _, x in entry['sets'] for r in x]
    more_music = gain > -.1 and any(cur_flat[i][1] >= 0 and secs(entry['tracks'][cur_flat[i][1]]) < 150
                                    for i in cut if i < len(cur_flat))  # a cut-short song that plays today
    if len(assign) < cur_m or not (gain >= MARGIN or (len(assign) > cur_m and new_q >= cur_q) or doubles(entry) or more_music):
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


JUNK = re.compile(r'(?i)^\W*(see\b.*|unknown\b.*|unk|n/?a|none|\?+|-+|various|anon(ymous)?)\W*$')
CREDIT = re.compile(r'(?i)^\W*((source\s*(&|and)\s*)?(dts\s*(&|and)\s*)?(original\s+|concert\s+|analog\s+)?(recording|recorded|taped|taper|'
                    r'matrix(ing|ed)?|mtx|transfer(red|s)?|xfer|remaster(ed)?|mix(ed)?|mastering|seeded|by)'
                    r'(\s+(and|&)\s+\w+)?\s*(by|:)?\s*)+')
NOT_A_NAME = re.compile(r'(?i)\b(sbd|aud|soundboard|audience|dts|matrix|mtx|source|src|mix|cdr?|mics?|info|unknown|thanks|'
                        r'seeds?|collection|crew|reel|dat|mono|stereo|channel)\b|@|https?:|www\.')
MONTH = (r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|'
         r'nov(?:ember)?|dec(?:ember)?)\.?(?=\s*(?:\d|$))')  # only a date: 'April 2021', not 'Marcus'


def who(v):
    """A person's name from a taper/transferer field, minus the 'Recording by' / 'Matrix by' boilerplate, or ''."""
    v = re.sub(r'\S+@\S+|https?://\S+|www\.\S+', ' ', text(v) or '')  # never show an email or link
    m = re.search(r'(?i)\bby\s+(.+)', v)  # 'FOB recording by X', 'Pitch correction by X', 'Recorded for Y by X'
    v = CREDIT.sub('', m.group(1) if m else v).strip()  # 'FOB recording by X', 'Transferred/Edited by X'
    v = re.split(r'[:;,(\[]|\s+\d|\s+-\s|\s+' + MONTH + r'|\s+(?:and|&)\s+(?=\w+\s+\w+\s+(?:and|&))|\s+(?:[\w/]+\s+){0,2}?(?:correct\w*|repair\w*|master\w*|remaster\w*|edit\w*|transfer\w*|patch\w*|pathing|seed\w*|provided|restor\w*|mix\w*|matrix\w*|record\w*|tap\w*|adjust\w*|suppl\w*|shn|flac|eac)\s+by\s|(?<=[a-z]{2})\.\s', v, flags=re.I)[0]
    v = re.sub(r'\s+', ' ', v).strip(' .-/')[:40]
    v = v + '.' if re.search(r'\s[A-Z]$', v) else v  # 'Andrew F.'
    return '' if len(v) < 2 or JUNK.match(v) or NOT_A_NAME.search(v) else v


def label(u):
    """Who made the tape, as briefly as the upload says: 'Taped by X', 'Matrix by X', 'Transfer by X', or its source."""
    taper, xfer, src = who(u.get('taper')), who(u.get('transferer')), text(u.get('source'))
    if re.search(r'(?i)(^|[._-])(5-1|dts)([._-]|$)|surround', u['identifier'] + ' ' + (text(u.get('transferer')) or '')):
        return 'Surround mix (5.1)'
    matrix = re.search(r'(?i)(^|[._-])(mtx|matrix)([._-]|$)', u['identifier'])
    if matrix and xfer:
        return 'Matrix by ' + xfer
    if taper:
        return 'Taped by ' + taper
    if xfer:
        return xfer if re.search(r'\d', xfer) else 'Transfer by ' + xfer
    src = re.sub(r'(?i)^(set|disc|cd)\s*\d+\s*[:-]?\s*', '', re.split(r'[;>]|-->', re.sub(r'(?i)\s*\(see[^)]*\)', '', src or ''))[0]).strip()
    src = re.sub(r'(?i)^(main\s+)?(lineage|source|src|recording info)\s*(#?\d+)?\s*:\s*', '', src)
    src = re.sub(r'^KG (?=\d)', 'AKG ', src)  # a mangled 'AKG' in some old uploads
    if JUNK.match(src) or re.search(r'(?i)unknown|info\b|^recording', src) or len(re.sub(r'(?i)\b(sbd|aud|soundboard|audience|matrix|mtx|master|unknown|source|dat|cdr?|pcm|reel|see|info|file|notes?|recording|recorded|cassette|analog|digital)\b|\W', '', src)) < 3:
        ws = [w for w in re.split(r'[._-]', u['identifier'].lower())[1:] if w.isalpha() and len(w) > 3
              and w not in STOP]
        return ('via ' + ws[0].title()) if ws else ''
    return src[:40]


STOP = {'sbeok', 'shnf', 'flac', 'flacf', 'late', 'early', 'show', 'partial', 'remaster', 'master', 'soundboard', 'audience',
        'matrix', 'fixed', 'retracked', 'sbefail', 'unknown', 'unkn', 'betty', 'board', 'blend', 'patch', 'shure', 'senn',
        'schoeps', 'neumann', 'akgck', 'nakcm', 'sony', 'binaural', 'stereo', 'mono', 'digital', 'analog', 'composite'}


def alt_tapes(date, current):
    """Every tape of a show for the tape switcher: [[id, type, rating, reviews, label, versions, partial, reviewers' note], ...],
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
            int(u.get('num_reviews') or 0), lab, n, int(bool(re.search(r'(?i)(^|[._-])(s|set)\d([._-]|$)|partial', u['identifier']))),
            comments(u['identifier'])[1] if (u.get('num_reviews') or 0) >= 2 else '']
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
    fixed = sum(fix_doubles(e) for e in setlists.values())
    print(f'{fixed} songs no longer play twice')
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
