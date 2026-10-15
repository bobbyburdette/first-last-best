"""Refresh Best vote counts and the two runner-up picks from HeadyVersion.

Runners-up are the next two highest-voted shows (after the Best) that have the song as a
labeled track on archive.org, using the same tape preference as upgrade_tapes.py. If a
song's #1 has changed, it is reported and left alone for a human to decide.

    python3 tools/refresh_runnersup.py                      # dry run
    python3 tools/refresh_runnersup.py --apply
    python3 tools/refresh_runnersup.py --only "Dark Star"   # one song
"""
import argparse
import datetime
import html
import re
import time

import flb

MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'march': 3, 'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6,
          'jul': 7, 'july': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12}
ROW = re.compile(r'show_score_(\d+)">\s*(\d+).*?show_date">\s*<a href="/show/(\d+)/[^"]+"[^>]*>\s*([^<]+?)\s*</a>', re.S)


def parse_rankings(page):
    rows = []
    for _, votes, show, label in ROW.findall(page):
        label = html.unescape(' '.join(label.split()))
        m = re.match(r'([A-Za-z]+)\.? (\d+), (\d{4})', label)
        month = MONTHS.get(m.group(1).lower()) if m else None
        if not month:
            continue
        rows.append({'date': f'{m.group(3)}-{month:02d}-{int(m.group(2)):02d}', 'votes': int(votes), 'show': show,
                     'venue': label.split(' - ', 1)[1] if ' - ' in label else ''})
    return rows


def resolve(song, row):
    for u in sorted(flb.uploads_for_date(row['date']), key=flb.rank_key):
        if flb.risky_source(u['identifier']):
            continue
        track = flb.find_track(u['identifier'], flb.song_names(song))
        if track:
            ident = u['identifier']
            return {'date': row['date'], 'venue': row['venue'], 'votes': row['votes'],
                    'headyHref': f"https://headyversion.com/show/{row['show']}/archive/",
                    'audio': flb.audio_url(ident, track['name']), 'track': track['title'],
                    'duration': track['length'], 'combined': track['title'].rstrip().endswith('>'),
                    'identifier': ident, 'recording': f'https://archive.org/details/{ident}'}
    return None


def refresh(song, today):
    best = song['best']
    rows = parse_rankings(flb.http_get(best['source']))
    if not rows:
        return 'no rankings parsed'
    top = [r['date'] for r in rows if r['votes'] == rows[0]['votes']]
    if best['date'] not in top:
        return f"#1 is now {rows[0]['date']} ({rows[0]['votes']} votes), was {best['date']}"
    best['votes'] = next(r['votes'] for r in rows if r['date'] == best['date'])
    best['checkedAt'] = today
    old = {r['date']: r for r in best.get('runnersUp', [])}
    picked, skipped, seen = [], [], {best['date']}
    for row in rows[:12]:
        if row['date'] in seen:
            continue
        seen.add(row['date'])
        r = {**old[row['date']], 'votes': row['votes']} if row['date'] in old else resolve(song, row)
        if r:
            picked.append(r)
        else:
            skipped.append(row['date'])
        if len(picked) == 2:
            break
    changed = [r['date'] for r in picked] != list(old)
    best['runnersUp'] = picked
    best['runnersUpCheckedAt'] = today
    return f"runners-up {[r['date'] for r in picked]}" + (' (changed)' if changed else '') + \
        (f' skipped {skipped}' if skipped else '')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--only', help='song name')
    args = ap.parse_args()
    today = datetime.date.today().isoformat()
    songs = flb.load_songs()
    for song in songs:
        best = song.get('best') or {}
        if song.get('kind') == 'sequence' or best.get('sourceType') != 'headyversion':
            continue
        if args.only and song['name'] != args.only:
            continue
        try:
            print(f"{song['name']}: {refresh(song, today)}")
        except Exception as e:
            print(f"{song['name']}: ERROR {e}")
        time.sleep(1.5)  # be gentle with HeadyVersion
    if args.apply:
        flb.save_songs(songs)
        flb.bump_data_version('songs.json')
        print('Applied. Run tools/check_audio.py next.')
    else:
        print('\nDry run. Re-run with --apply to write changes.')


if __name__ == '__main__':
    main()
