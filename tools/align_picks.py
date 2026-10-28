"""Point First/Last/Best picks at their show's main tape when that tape sounds as good or better.

The performance (the date) never changes, only which recording of it plays, so a card and its show page
play the same tape. Uses data/setlists.json to find the song on the show tape. A move is held for a
listen when the track length differs by more than 30%, unless the card's current track runs two songs together.
Tapes kept after a listen (tools/listened.json) are left alone.

    python3 tools/align_picks.py          # dry run
    python3 tools/align_picks.py --apply  # write songs.json and bump its version
"""
import argparse
import json

import flb
from fetch_setlists import OUT as SETLISTS, title_key

LISTENED = flb.ROOT / 'tools' / 'listened.json'  # tape choices made by ear: "song|slot|date": keep or switch


def show_track(sl, names):
    keys = {title_key(n) for n in names}
    hits = [r[1] for _, rows in sl['sets'] for r in rows if r[1] >= 0 and title_key(r[0]) in keys]
    if not hits:
        return None
    i = max(hits, key=lambda i: flb.secs(sl['tracks'][i][2]))
    f, title, length = sl['tracks'][i]
    return {'name': f, 'title': title, 'length': flb.mmss(flb.secs(length))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    shows = {s['d']: s['id'] for s in flb.load_shows()}
    setlists = json.loads(SETLISTS.read_text())
    songs = flb.load_songs()
    listened = json.loads(LISTENED.read_text()) if LISTENED.exists() else {}
    moved, held = [], []
    for song in songs:
        if song.get('kind') == 'sequence':
            continue
        for slot, pick in flb.picks(song, runners=False):
            cur, date = pick.get('identifier'), pick.get('date')
            if listened.get(f"{song['name']}|{slot}|{date}") == 'keep':  # Bobby listened and kept this tape
                continue
            main_tape = shows.get(date)
            sl = setlists.get(date)
            if not (cur and main_tape and sl) or cur == main_tape or sl.get('id') != main_tape:
                continue
            if flb.is_upgrade(main_tape, cur):  # the card's tape is better (often a partial upload): keep it
                continue
            if flb.is_miller(cur) and not flb.is_miller(main_tape):  # never leave a Charlie Miller transfer
                continue
            track = show_track(sl, flb.song_names(song))
            if not track:
                held.append((song['name'], slot, date, 'song not found on the show tape'))
                continue
            was, now = flb.secs(pick.get('duration', '0')), flb.secs(track['length'])
            combined = '>' in (pick.get('track') or '') and now < was  # the card's track runs into the next song
            if was and abs(now - was) / was > 0.30 and not combined:
                held.append((song['name'], slot, date, f"length {pick.get('duration')} vs {track['length']} on {main_tape}"))
                continue
            better = flb.is_upgrade(cur, main_tape)
            rating = next((u for u in flb.uploads_for_date(date) if u['identifier'] == main_tape), None)
            moved.append((song['name'], slot, date, cur, main_tape, better))
            if args.apply:
                flb.set_pick_tape(pick, main_tape, track, rating)
    for name, slot, date, cur, new, better in moved:
        print(f"{'UPGRADE' if better else 'ALIGN  '} {name} [{slot}] {date}: {cur} -> {new}")
    for row in held:
        print('HELD    {} [{}] {}: {}'.format(*row))
    print(f"\n{sum(m[5] for m in moved)} upgrades, {sum(not m[5] for m in moved)} same-quality moves, {len(held)} held")
    if args.apply and moved:
        flb.save_songs(songs)
        flb.bump_data_version('songs.json')
        print('Applied. Run tools/build_tapes.py, tools/check_audio.py and tools/build_pages.py next.')
    elif not args.apply:
        print('Dry run. Re-run with --apply to write changes.')


if __name__ == '__main__':
    main()
