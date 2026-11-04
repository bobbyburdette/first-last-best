"""Add songs to songs.json: First and Last from The SetList Program, Best from HeadyVersion when the
song has a real vote there, otherwise the longest version on tape (labeled Longest, never Best).

    python3 tools/add_songs.py            # dry run: prints what each new song would get
    python3 tools/add_songs.py --apply    # writes songs.json

Songs are listed in NEW below: name, aliases (other spellings in setlists), and the HeadyVersion song
path when one exists. Songs already in songs.json are skipped, so it is safe to re-run.
"""
import argparse
import datetime
import html
import json
import re
import sys
import time
import urllib.parse

import flb
from fetch_setlists import OUT as SETLISTS, title_key

MIN_VOTES = 5  # a HeadyVersion #1 with fewer votes than this is not a real pick yet

# (name, aliases, HeadyVersion song path or None)
NEW = [
    ('Little Red Rooster', [], '/song/158/grateful-dead/little-red-rooster/'),
    ("Walkin' Blues", ['Walking Blues'], '/song/286/grateful-dead/walking-blues/'),
    ('Queen Jane Approximately', [], '/song/338/grateful-dead/queen-jane-approximately/'),
    ('C.C. Rider', ['CC Rider', 'C. C. Rider'], '/song/43/grateful-dead/c-c-rider/'),
    ('All Along The Watchtower', [], '/song/333/grateful-dead/all-along-the-watchtower/'),
    ('Slipknot!', ['Slipknot'], None),
    ('My Brother Esau', ['Brother Esau'], None),
    ('Long Way To Go Home', [], None),
    ("Gimme Some Lovin'", ['Gimme Some Loving'], '/song/100/grateful-dead/gimme-some-lovin/'),
    ('Picasso Moon', [], '/song/334/grateful-dead/picasso-moon/'),
    ('Next Time You See Me', [], '/song/194/grateful-dead/next-time-you-see-me/'),
    ('Far From Me', [], '/song/91/grateful-dead/far-from-me/'),
    ('Big Boss Man', [], '/song/22/grateful-dead/big-boss-man/'),
    ('Lazy River Road', [], '/song/344/grateful-dead/lazy-river-road/'),
    ('Smokestack Lightning', ["Smokestack Lightnin'"], '/song/247/grateful-dead/smokestack-lightnin/'),
    ('The Race Is On', [], '/song/215/grateful-dead/the-race-is-on/'),
    ('When Push Comes To Shove', [], '/song/300/grateful-dead/when-push-comes-to-shove/'),
    ('Dear Mr. Fantasy', ['Dear Mr Fantasy'], '/song/70/grateful-dead/dear-mr-fantasy/'),
    ('The Mighty Quinn', ['Quinn The Eskimo', 'Mighty Quinn'], None),
    ('Desolation Row', [], '/song/74/grateful-dead/desolation-row/'),
    ('Day Job', [], '/song/67/grateful-dead/day-job/'),
    ('Liberty', [], '/song/346/grateful-dead/liberty/'),
    ('Spoonful', [], '/song/375/grateful-dead/spoonful/'),
    ('The Last Time', ['This Could Be The Last Time', 'Last Time'], '/song/353/grateful-dead/last-time/'),
    ('Easy To Love You', [], '/song/83/grateful-dead/easy-to-love-you/'),
    ('Let The Good Times Roll', [], '/song/347/grateful-dead/let-the-good-times-roll/'),
    ('On The Road Again', [], '/song/201/grateful-dead/on-the-road-again/'),
    ('The Same Thing', [], '/song/231/grateful-dead/the-same-thing/'),
    ('The Weight', [], '/song/298/grateful-dead/the-weight/'),
    ('Easy Answers', [], '/song/343/grateful-dead/easy-answers/'),
    ("Maggie's Farm", [], '/song/367/grateful-dead/maggies-farm/'),
    ('Eternity', [], '/song/337/grateful-dead/eternity/'),
    ('Good Time Blues', [], None),
    ('Sing Me Back Home', [], '/song/244/grateful-dead/sing-me-back-home/'),
    ('Samba In The Rain', [], '/song/341/grateful-dead/samba-in-the-rain/'),
    ('Monkey And The Engineer', ['Monkey & The Engineer'], '/song/183/grateful-dead/monkey-and-the-engineer/'),
    ('I Fought The Law', [], '/song/380/grateful-dead/i-fought-the-law/'),
    ('I Will Take You Home', [], None),
    ('Broken Arrow', [], '/song/349/grateful-dead/broken-arrow/'),
    ('Satisfaction', ["(I Can't Get No) Satisfaction"], '/song/233/grateful-dead/satisfaction/'),
    ('Sunrise', [], '/song/254/grateful-dead/sunrise/'),
    ('Tons Of Steel', ['100000 Tons Of Steel'], None),
    ('Chinatown Shuffle', [], '/song/53/grateful-dead/chinatown-shuffle/'),
    ('From The Heart Of Me', [], '/song/98/grateful-dead/from-the-heart-of-me/'),
    ('King Bee', ["I'm A King Bee"], '/song/149/grateful-dead/king-bee/'),
    ('You Win Again', [], '/song/308/grateful-dead/you-win-again/'),
    ('We Can Run', [], '/song/356/grateful-dead/we-can-run/'),
    ('Just A Little Light', [], '/song/354/grateful-dead/just-a-little-light/'),
    ('Wave To The Wind', [], '/song/336/grateful-dead/wave-to-the-wind/'),
    ('Rain', [], '/song/214/grateful-dead/rain/'),
    ("Oh Babe, It Ain't No Lie", ["Oh Babe It Ain't No Lie"], '/song/16/grateful-dead/oh-babe-it-aint-no-lie/'),
    ('Lucy In The Sky With Diamonds', [], '/song/348/grateful-dead/lucy-in-the-sky-with-diamonds/'),
    ('Rosalie McFall', [], '/song/223/grateful-dead/rosalie-mcfall/'),
    ('Built To Last', [], '/song/42/grateful-dead/built-to-last/'),
    ('He Was A Friend Of Mine', [], '/song/113/grateful-dead/he-was-a-friend-of-mine/'),
    ("Mason's Children", [], '/song/170/grateful-dead/masons-children/'),
    ('Funiculi Funicula', [], None),
    ('Heaven Help The Fool', [], '/song/114/grateful-dead/heaven-help-the-fool/'),
    ('If The Shoe Fits', [], '/song/363/grateful-dead/if-the-shoe-fits/'),
    ('Been All Around This World', ["I've Been All Around This World"], None),
    ("Don't Need Love", [], '/song/78/grateful-dead/dont-need-love/'),
    ('That Would Be Something', [], '/song/318/grateful-dead/that-would-be-something/'),
    ("Nobody's Fault But Mine", [], '/song/197/grateful-dead/nobodys-fault-but-mine/'),
    ('Wave That Flag', [], None),
    ("You Ain't Woman Enough", ["You Ain't Woman Enough To Take My Man"], None),
    ('Gloria', [], '/song/101/grateful-dead/gloria/'),
    ("It's A Sin", [], None),
    ('Revolution', [], '/song/217/grateful-dead/revolution/'),
    ("Baba O'Riley", [], None),
    ('Tomorrow Never Knows', [], None),
    ('Silver Threads And Golden Needles', ['Silver Threads'], None),
    ('Two Souls In Communion', [], '/song/275/grateful-dead/two-souls-in-communion/'),
    ("Childhood's End", [], '/song/362/grateful-dead/childhoods-end/'),
    ('She Belongs To Me', [], '/song/240/grateful-dead/she-belongs-to-me/'),
    ("It's A Man's World", [], '/song/138/grateful-dead/its-a-mans-world/'),
    ('Cold Jordan', [], '/song/56/grateful-dead/cold-jordan/'),
]
# Hand-picked HeadyVersion categories that cover more than this one song are left out on purpose (U.S. Blues
# includes Wave That Flag; Baba O'Riley and Tomorrow Never Knows share one category), so those use Longest.

SL = 'https://www.setlists.net/'
HV = 'https://headyversion.com'
LI = re.compile(r"<li><a href='\./\?show_id=(\d+)'>(\d\d)/(\d\d)/(\d\d)-\s*(.*?)</a></li>")


def history_url(name):
    return SL + '?' + urllib.parse.urlencode({'search': 'true', 'songs': name, 'songs_exact': 'true'})


def history(name):
    """{date: (show_id, 'Venue - City, ST')} for every show The SetList Program lists the song at."""
    path = flb.CACHE / 'history' / (re.sub(r'[^A-Za-z0-9]', '_', name) + '.html')
    if path.exists():
        page = path.read_text()
    else:
        page = flb.http_get(history_url(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page)
        time.sleep(1)  # be gentle with setlists.net
    out = {}
    for sid, m, d, y, where in LI.findall(page):
        out[f'19{y}-{m}-{d}'] = (sid, html.unescape(' '.join(where.split())))
    return out


def tape_pick(date, names):
    """Best playable upload of the song on that date, same preference as the rest of the site."""
    for u in sorted(flb.uploads_for_date(date), key=flb.rank_key):
        ident = u['identifier']
        if flb.risky_source(ident):
            continue
        tr = flb.find_track(ident, names)
        if tr:
            p = {'audio': flb.audio_url(ident, tr['name']), 'track': tr['title'], 'duration': tr['length'],
                 'combined': tr['title'].rstrip().endswith('>'), 'identifier': ident,
                 'recording': f'https://archive.org/details/{ident}'}
            if u.get('avg_rating') is not None:
                p['rating'], p['reviews'] = u['avg_rating'], u.get('num_reviews') or 0
            return p
    return None


def slot(date, sid, where, names):
    p = {'date': date, 'venue': where, 'source': f'{SL}?show_id={sid}'}
    tape = tape_pick(date, names)
    if tape:
        p.update(tape)
    else:
        p['unavailable'] = True
        p['archiveSearch'] = f'https://archive.org/details/GratefulDead?query=date%3A{date}'
    p['showId'] = f'gd-{date}'
    return p


def split_where(where):
    parts = where.split(' - ')
    return parts[0], ' - '.join(parts[1:])


def heady_best(name, names, path, today, hist):
    from refresh_runnersup import parse_rankings, resolve
    rows = parse_rankings(flb.http_get(HV + path))
    time.sleep(1.5)  # be gentle with HeadyVersion
    if not rows or rows[0]['votes'] < MIN_VOTES:
        return None, (f"top has {rows[0]['votes']} votes" if rows else 'no rankings')
    song = {'name': name, 'aliases': names[1:]}
    picked = []
    for row in rows[:12]:
        if any(r['date'] == row['date'] for r in picked):
            continue
        r = resolve(song, row)
        if r:
            picked.append(r)
        if len(picked) == 3:
            break
    if not picked or picked[0]['votes'] < MIN_VOTES:
        return None, 'no top-voted show has a labeled tape'
    top, runners = picked[0], picked[1:]
    ties = [{'date': r['date'], 'votes': r['votes']} for r in rows[1:] if r['votes'] == top['votes'] and r['date'] != top['date']]
    where = hist.get(top['date'], (None, ''))[1]
    venue_name, city = split_where(where) if where else (top['venue'], '')
    best = {'date': top['date'], 'venue': where or top['venue'], 'source': HV + path, 'sourceType': 'headyversion',
            'votes': top['votes'], 'checkedAt': today, 'category': name,
            'sourceShow': top['headyHref'], 'ties': ties,
            **{k: top[k] for k in ('audio', 'track', 'duration', 'combined', 'identifier', 'recording')},
            'venueName': venue_name, 'city': city, 'showId': f"gd-{top['date']}",
            'runnersUp': [{k: v for k, v in r.items()} for r in runners if r['votes'] >= MIN_VOTES],
            'runnersUpCheckedAt': today}
    return best, f"HeadyVersion {top['date']} ({top['votes']} votes)"


def longest_best(names, setlists, hist):
    """The longest single-song tape track in the site's setlists (a track shared with a segue or a
    sandwich doesn't count)."""
    keys = {title_key(n) for n in names}
    cands = []
    for date, sl in setlists.items():
        rows = [r for _, rs in sl['sets'] for r in rs]
        hits = [i for i, r in enumerate(rows) if title_key(r[0]) in keys]
        if len(hits) != 1 or not sl.get('id'):
            continue
        i, idx = hits[0], rows[hits[0]][1]
        if idx < 0 or idx >= len(sl['tracks']) or (i + 1 < len(rows) and rows[i + 1][1] == -1):
            continue
        tr = sl['tracks'][idx]
        if title_key(tr[1].rstrip(' >-')) not in keys:
            continue
        cands.append((flb.secs(tr[2]), date))
    # A track far longer than the song usually runs has something else on it (tuning, Drums, a jam)
    lens = sorted(s for s, _ in cands)
    cands = [c for c in cands if lens and c[0] <= 1.8 * lens[len(lens) // 2]]
    if not cands:
        return None, 'no single-song track on tape'
    date = max(cands)[1]
    tape = tape_pick(date, names)
    if not tape:
        return None, f'longest {date} has no matched tape'
    sid, where = hist.get(date, ('', ''))
    venue, city = split_where(where) if where else ('', '')
    p = {'date': date, 'venue': where, 'source': f'{SL}?show_id={sid}' if sid else '', 'sourceType': 'longest',
         'note': f"Longest version on tape ({tape['duration']}). Not enough HeadyVersion votes yet to name a fan favorite.",
         **tape, 'venueName': venue, 'city': city, 'showId': f'gd-{date}'}
    p.pop('rating', None)
    p.pop('reviews', None)
    return p, f"Longest {date} ({tape['duration']})"


def build(name, aliases, path, setlists, today):
    names = [name, *aliases]
    hist = {}
    for n in names:
        hist.update(history(n))
    if not hist:
        return None, 'not found in The SetList Program'
    dates = sorted(hist)
    first, last = dates[0], dates[-1]
    song = {'name': name}
    if aliases:
        song['aliases'] = aliases
    song['history'] = history_url(name)
    song['count'] = len(dates)
    song['first'] = slot(first, *hist[first], names)
    song['last'] = slot(last, *hist[last], names)
    best, why = (heady_best(name, names, path, today, hist) if path else (None, 'no HeadyVersion category'))
    if not best:
        best, why2 = longest_best(names, setlists, hist)
        why = f'{why}; {why2}'
    song['best'] = best
    song['rank'] = None
    return song, why


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--only')
    args = ap.parse_args()
    today = datetime.date.today().isoformat()
    songs = flb.load_songs()
    have = {title_key(n) for s in songs for n in flb.song_names(s)}
    setlists = json.loads(SETLISTS.read_text())
    added = []
    for name, aliases, path in NEW:
        if args.only and name != args.only:
            continue
        if title_key(name) in have:
            continue
        try:
            song, why = build(name, aliases, path, setlists, today)
        except Exception as e:
            print(f'{name}: ERROR {e}')
            continue
        if not song:
            print(f'{name}: SKIPPED ({why})')
            continue
        f, l, b = song['first'], song['last'], song['best']
        print(f"{name}: {song['count']} shows · first {f['date']}{'' if f.get('audio') else ' (no tape)'}"
              f" · last {l['date']}{'' if l.get('audio') else ' (no tape)'} · {why if b else 'NO BEST: ' + why}")
        added.append(song)
    if args.apply and added:
        songs += added
        flb.save_songs(songs)
        flb.bump_data_version('songs.json')
        print(f'Added {len(added)} songs ({len(songs)} total).')
    elif not args.apply:
        print(f'\nDry run: {len(added)} songs. Re-run with --apply to write them.')


if __name__ == '__main__':
    sys.exit(main())
