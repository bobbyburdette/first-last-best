"""Build the First Last Best archive: everything the site knows about the Grateful Dead as plain tables
(CSV) plus one SQLite database, with the source of every fact, so it outlives this site and any of its sources.

    python3 tools/build_archive.py OUT_DIR             # private archive (all data + raw source snapshots)
    python3 tools/build_archive.py OUT_DIR --public    # public copy: no HeadyVersion vote counts, no snapshots

Tables (see the README written into OUT_DIR for every column):
  sources        where facts come from, and any terms attached
  shows          one row per show date
  songs          one row per song or live sequence on the site
  song_aliases   other titles a song appears under in setlists
  performances   every song in every setlist the site has, in order, with its tape track when matched
  tapes          archive.org recordings used, and what kind they are
  picks          First, Last, Best (or Longest) and runner-up versions of each song
New sources (JerryBase, corrections) are added as rows with their own source id; nothing is overwritten.
"""
import argparse
import csv
import datetime
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import flb
from build_pages import slug
from fetch_setlists import OUT as SETLISTS, title_key

SOURCES = [
    ('setlistprogram', 'The SetList Program', 'https://www.setlists.net/',
     'Setlists (sets, song order) and the full list of dates each song was played. First and Last dates.', ''),
    ('archive', 'Internet Archive, Grateful Dead collection', 'https://archive.org/details/GratefulDead',
     'Recordings, track titles and lengths, ratings.', 'Audio is streamed from archive.org, never copied.'),
    ('headyversion', 'HeadyVersion', 'https://headyversion.com/',
     'Fan votes for the best version of each song (Best and runners-up).',
     'Vote counts are left out of the public copy unless HeadyVersion agrees.'),
    ('deaddisc', 'Grateful Dead Family Discography', 'https://www.deaddisc.com/',
     'Songwriters and first release of each song.', ''),
    ('deadnet', 'dead.net', 'https://www.dead.net/songs',
     'Official song pages; used for lyrics links only.', 'Lyrics are linked, never copied.'),
    ('rollingstone', 'Rolling Stone, 100 Best Grateful Dead Songs', 'https://open.spotify.com/playlist/57DKri7bovfPjr01HdwksP',
     'Rank of a song in that list.', ''),
    ('tape', 'Archive.org track titles', 'https://archive.org/details/GratefulDead',
     'Setlist read from a tape\'s track titles when The SetList Program has none for that date.', 'Less reliable.'),
    ('flb', 'First Last Best', 'https://firstlastbest.com/',
     'Our own work: tape matching, Longest picks, corrections.', ''),
    ('jerrybase', 'JerryBase', 'https://jerrybase.com/',
     'Setlists (sets, order, segues) and the full list of public concerts.',
     'Downloaded by hand plus one light page pull the owner OK\'d. Credit and link JerryBase on every show that uses it.'),
]

COLUMNS = {
    'sources': ['source_id', 'name', 'url', 'provides', 'terms'],
    'shows': ['date', 'venue', 'city', 'state_or_country', 'main_tape', 'setlist_source', 'site_url'],
    'songs': ['song_id', 'name', 'kind', 'writers', 'first_release', 'credits_source_url', 'lyrics_url',
              'setlist_program_count', 'setlist_program_url', 'rolling_stone_rank', 'site_url'],
    'song_aliases': ['song_id', 'alias'],
    'performances': ['date', 'set_name', 'position', 'title_as_listed', 'song_id', 'segue_into_next',
                     'tape', 'track_file', 'track_title', 'track_seconds', 'source_id'],
    'tapes': ['identifier', 'date', 'recording_type', 'details', 'archive_url', 'used_for'],
    'picks': ['song_id', 'pick', 'date', 'venue', 'tape', 'track_title', 'duration', 'votes', 'votes_checked',
              'note', 'source_id', 'source_url'],
}
PUBLIC_DROP = {'picks': {'votes', 'votes_checked'}}
KIND_SOURCE = {'first': 'setlistprogram', 'last': 'setlistprogram'}


def split_place(c):
    parts = [p.strip() for p in (c or '').rsplit(',', 1)]
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], '')


def secs(x):
    return int(flb.secs(x)) if x else ''


def recording_type(ident):
    return flb.SOURCE_NAMES[flb.source_class(ident)] + (' (Charlie Miller)' if flb.is_miller(ident) else '')


README = """# First Last Best: Grateful Dead archive

Everything firstlastbest.com knows about the Grateful Dead's live history, as plain tables anyone can open:
every show, every setlist, every time each song was played, which tape has it, and each song's first, last
and best (or longest) live version. Every fact says where it came from.

{visibility}

Built {built} from site commit {commit}.

## Files

- `data/*.csv`: one spreadsheet per table (UTF-8, comma-separated, first row is the column names).
- `grateful-dead.sqlite`: the same tables in one SQLite database, plus a `song_history` view.
- `MANIFEST.json`: when it was built and how many rows each table has.
{snapshots_line}
## Tables

{tables}

## Sources

{sources}

## Rules for adding data

1. Never overwrite a fact from one source with another. Add the new rows with their own `source_id`
   (for example `jerrybase`) and decide which one the site shows in the site's tools.
2. Dates are `YYYY-MM-DD`. A song is linked by `song_id` (the site's URL slug, e.g. `dark-star`).
3. Lyrics and audio are never copied here. Link to them.
4. JerryBase data comes only from what JerryBase sends us. Never scrape JerryBase.

## Known gaps

- `performances` covers the {shows} shows that have a tape on archive.org. The Dead played roughly 2,300
  shows. `songs.setlist_program_count` is the full count from The SetList Program.
- First and Last come from The SetList Program and can miss early or disputed dates (for example
  Pigpen-era songs listed under other titles).
- `segue_into_next` is read from tape track titles ("Song >"), so it is blank when no tape matched.
"""

DOCS = {
    'sources': {'source_id': 'Short id used in other tables.', 'name': 'Source name.', 'url': 'Where it lives.',
                'provides': 'What we take from it.', 'terms': 'Conditions attached.'},
    'shows': {'date': 'Show date.', 'venue': 'Venue name.', 'city': 'City.', 'state_or_country': 'US state or country.',
              'main_tape': 'archive.org identifier of the tape the site plays.',
              'setlist_source': 'setlistprogram, or tape when the setlist was read from track titles.',
              'site_url': 'Show page on firstlastbest.com.'},
    'songs': {'song_id': 'Stable id (URL slug).', 'name': 'Song title.', 'kind': 'song or sequence (e.g. Help > Slip > Frank).',
              'writers': 'Songwriters, " / " separated.', 'first_release': 'First release, "Album, Year".',
              'credits_source_url': 'Page the credits came from.', 'lyrics_url': 'Lyrics on dead.net, when it has them.',
              'setlist_program_count': 'Shows The SetList Program lists the song at.',
              'setlist_program_url': 'That list.', 'rolling_stone_rank': 'Rank in Rolling Stone\'s 100 best, if listed.',
              'site_url': 'Song page on firstlastbest.com.'},
    'song_aliases': {'song_id': 'Song.', 'alias': 'Another title the song appears under in setlists.'},
    'performances': {'date': 'Show date.', 'set_name': 'Set 1, Set 2, Set 3, Encore (blank if unknown).',
                     'position': 'Order in the show, starting at 1.', 'title_as_listed': 'Title exactly as the setlist has it.',
                     'song_id': 'Linked song, blank when the site has no page for it (jams, Drums, rarities).',
                     'segue_into_next': '1 if the tape marks a segue (>) into the next song.',
                     'tape': 'archive.org identifier the track is on.', 'track_file': 'File name on that tape.',
                     'track_title': 'Track title on that tape.', 'track_seconds': 'Track length (includes any tuning or crowd).',
                     'source_id': 'Where the setlist came from.'},
    'tapes': {'identifier': 'archive.org identifier.', 'date': 'Show date.',
              'recording_type': 'Soundboard, Matrix, Audience or Unknown (from the identifier), and Charlie Miller transfers.',
              'details': 'Taper, transfer and notes from the tape\'s page.', 'archive_url': 'Tape page.',
              'used_for': 'show, setlist and/or pick.'},
    'picks': {'song_id': 'Song.', 'pick': 'first, last, best, longest, runner_up_1, runner_up_2.',
              'date': 'Show date.', 'venue': 'Venue as the source lists it.', 'tape': 'archive.org identifier played.',
              'track_title': 'Track title.', 'duration': 'Track length.',
              'votes': 'HeadyVersion votes (private copy only).', 'votes_checked': 'Date the votes were read (private copy only).',
              'note': 'Notes, e.g. why a date was chosen.', 'source_id': 'Where the pick came from.',
              'source_url': 'The exact page.'},
}


def build(public):
    songs, shows = flb.load_songs(), flb.load_shows()
    setlists = json.loads(SETLISTS.read_text())
    tape_notes = json.loads(flb.TAPES.read_text())
    rows = {k: [] for k in COLUMNS}
    rows['sources'] = [dict(zip(COLUMNS['sources'], s)) for s in SOURCES]

    by_key = {}
    for s in songs:
        sid = slug(s['name'])
        cr = s.get('credits') or {}
        rows['songs'].append({
            'song_id': sid, 'name': s['name'], 'kind': s.get('kind') or 'song', 'writers': cr.get('writers', ''),
            'first_release': cr.get('release', ''), 'credits_source_url': cr.get('source', ''),
            'lyrics_url': s.get('lyrics', ''), 'setlist_program_count': s.get('count') or '',
            'setlist_program_url': s.get('history', ''), 'rolling_stone_rank': s.get('rank') or '',
            'site_url': f'https://firstlastbest.com/song/{sid}/'})
        for a in s.get('aliases', []):
            rows['song_aliases'].append({'song_id': sid, 'alias': a})
        if s.get('kind') != 'sequence':
            for n in flb.song_names(s):
                by_key.setdefault(title_key(n), sid)
        for k, p in flb.picks(s):
            if not p or not p.get('date'):
                continue
            best = k == 'best'
            longest = best and p.get('sourceType') == 'longest'
            src = KIND_SOURCE.get(k, 'flb' if longest else 'headyversion')
            if src == 'setlistprogram' and 'setlists.net' not in (p.get('source') or ''):
                src = 'flb'  # a First/Last set by hand from another reference (its note and URL say which)
            rows['picks'].append({
                'song_id': sid, 'pick': 'longest' if longest else k.replace('runnerUp', 'runner_up_'),
                'date': p['date'], 'venue': p.get('venue', ''), 'tape': p.get('identifier', ''),
                'track_title': p.get('track', ''), 'duration': p.get('duration', ''),
                'votes': p.get('votes', '') if not longest else '',
                'votes_checked': (p.get('checkedAt') or (s.get('best') or {}).get('runnersUpCheckedAt', '')) if src == 'headyversion' else '',
                'note': p.get('note', ''), 'source_id': src,
                'source_url': p.get('source') or p.get('headyHref') or ''})

    tapes = {}

    def tape(ident, date, used):
        if not ident:
            return
        t = tapes.setdefault(ident, {'identifier': ident, 'date': date, 'recording_type': recording_type(ident),
                                     'details': ' · '.join(v for v in (tape_notes.get(ident) or {}).values()
                                                           if isinstance(v, str))[:300],
                                     'archive_url': f'https://archive.org/details/{ident}', 'used_for': set()})
        t['used_for'].add(used)

    for s in shows:
        city, st = split_place(s['c'])
        sl = setlists.get(s['d']) or {}
        rows['shows'].append({'date': s['d'], 'venue': s['v'], 'city': city, 'state_or_country': st,
                              'main_tape': s.get('id') or '',
                              'setlist_source': (sl.get('source') or ('setlistprogram' if sl.get('full') else 'tape')) if sl.get('sets') else '',
                              'site_url': f'https://firstlastbest.com/show/{s["d"]}/'})
        tape(s.get('id'), s['d'], 'show')
    for p in rows['picks']:
        tape(p['tape'], p['date'], 'pick')

    for date, sl in sorted(setlists.items()):
        ids = sl.get('tapes') or [sl.get('id')]
        pos = 0
        for set_name, set_rows in sl.get('sets', []):
            for title, idx, segue in set_rows:
                pos += 1
                tr = sl['tracks'][idx] if sl.get('id') and 0 <= idx < len(sl.get('tracks', [])) else None
                ident = ids[tr[3]] if tr and len(tr) > 3 else (sl.get('id') if tr else '')
                rows['performances'].append({
                    'date': date, 'set_name': set_name, 'position': pos, 'title_as_listed': title,
                    'song_id': by_key.get(title_key(title), ''), 'segue_into_next': int(bool(segue)) if tr else '',
                    'tape': ident or '', 'track_file': tr[0] if tr else '', 'track_title': tr[1] if tr else '',
                    'track_seconds': secs(tr[2]) if tr else '',
                    'source_id': sl.get('source') or ('setlistprogram' if sl.get('full') else 'tape')})
                if ident:
                    tape(ident, date, 'setlist')
    rows['tapes'] = [{**t, 'used_for': ', '.join(sorted(t['used_for']))} for t in sorted(tapes.values(), key=lambda t: (t['date'], t['identifier']))]

    if public:
        for table, drop in PUBLIC_DROP.items():
            for r in rows[table]:
                for c in drop:
                    r[c] = ''
    return rows


def write(rows, out, public):
    data = out / 'data'
    data.mkdir(parents=True, exist_ok=True)
    for table, cols in COLUMNS.items():
        cols = [c for c in cols if not (public and c in PUBLIC_DROP.get(table, ()))]
        with open(data / f'{table}.csv', 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows[table])
    db = out / 'grateful-dead.sqlite'
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    for table, cols in COLUMNS.items():
        cols = [c for c in cols if not (public and c in PUBLIC_DROP.get(table, ()))]
        con.execute(f'CREATE TABLE {table} ({", ".join(cols)})')
        con.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" * len(cols))})',
                        [[r.get(c, '') for c in cols] for r in rows[table]])
    con.executescript('''
        CREATE INDEX perf_song ON performances(song_id);
        CREATE INDEX perf_date ON performances(date);
        CREATE VIEW song_history AS
          SELECT s.song_id, s.name, COUNT(DISTINCT p.date) AS shows_on_site,
                 MIN(p.date) AS first_on_site, MAX(p.date) AS last_on_site
          FROM songs s JOIN performances p ON p.song_id = s.song_id GROUP BY s.song_id;
    ''')
    con.commit()
    con.close()


def snapshots(out):
    """Raw copies of what we pulled from each source, so the tables can be rebuilt if a source disappears.
    Dead.net pages are reduced to title, writers and URL (their lyrics are not kept)."""
    snap = out / 'snapshots'  # added to, never cleared: a later session's cache may hold only part of it
    for name in ('history', 'deaddisc', 'meta', 'uploads'):
        src = flb.CACHE / name
        if src.exists():
            shutil.copytree(src, dirs_exist_ok=True, dst=snap / {'history': 'setlistprogram-song-history', 'deaddisc': 'deaddisc',
                                         'meta': 'archive-metadata', 'uploads': 'archive-uploads-by-date'}[name])
    keep = snap / 'deadnet' / 'song-pages.json'
    pages = {p['path']: p for p in (json.loads(keep.read_text()) if keep.exists() else [])}
    for f in sorted((flb.CACHE / 'deadnet').glob('_song_*.html')):
        t = f.read_text()
        field = lambda n: (re.search(rf'field--name-field-{n}\s.*?field__item">(.*?)</div>', t, re.S) or [None, ''])[1].strip()
        title = (re.search(r'<title>([^|<]*)', t) or [None, ''])[1].strip()
        path = '/' + f.stem.lstrip('_').replace('_', '/', 1).replace('_', '-')
        pages[path] = {'path': path, 'title': title, 'lyrics_by': field('lyrics-by'), 'music_by': field('music-by'),
                       'has_lyrics': bool(re.search(r'field--name-field-lyrics\s', t))}
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text(json.dumps(sorted(pages.values(), key=lambda p: p['path']), indent=1, ensure_ascii=False))
    for f in ('songs.json', 'shows.json', 'tapes.json', 'data/setlists.json'):
        shutil.copy(flb.ROOT / f, snap / ('site-' + Path(f).name))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--public', action='store_true')
    args = ap.parse_args()
    out = Path(args.out)
    rows = build(args.public)
    write(rows, out, args.public)
    if not args.public:
        snapshots(out)
    commit = subprocess.run(['git', '-C', str(flb.ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    manifest = {'built': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
                'site_commit': commit, 'public': args.public, 'counts': {t: len(r) for t, r in rows.items()}}
    (out / 'MANIFEST.json').write_text(json.dumps(manifest, indent=1) + '\n')
    tables = '\n\n'.join(f'### {t}\n\n| column | meaning |\n|---|---|\n' + '\n'.join(
        f'| `{c}` | {DOCS[t][c]} |' for c in COLUMNS[t] if not (args.public and c in PUBLIC_DROP.get(t, ())))
        for t in COLUMNS)
    sources = '\n'.join(f'- **{s[1]}** (`{s[0]}`, {s[2]}): {s[3]}' + (f' {s[4]}' if s[4] else '') for s in SOURCES)
    (out / 'README.md').write_text(README.format(
        visibility='Public copy: HeadyVersion vote counts and raw source snapshots are left out.' if args.public
        else 'Private copy: includes HeadyVersion vote counts and raw snapshots of each source. Do not publish as is; '
             'make the public copy with `--public`.',
        built=manifest['built'][:10], commit=commit, tables=tables, sources=sources, shows=len(rows['shows']),
        snapshots_line='' if args.public else '- `snapshots/`: raw copies of what was pulled from each source, to rebuild from if a source disappears.\n'))
    print(json.dumps(manifest['counts']))


if __name__ == '__main__':
    main()
