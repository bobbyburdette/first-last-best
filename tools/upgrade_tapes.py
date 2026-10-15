"""Swap song picks (and optionally Shows on this day) to better recordings of the same show.

Order of preference: Miller soundboard > soundboard > matrix > audience. A pick only moves
when the new tape is strictly better, has the song as a labeled track, and the track length
is within 30% of the current one. Monitor mixes and half-aud/half-sbd uploads are skipped.

    python3 tools/upgrade_tapes.py                 # dry run, prints the plan
    python3 tools/upgrade_tapes.py --apply         # write songs.json and bump its version
    python3 tools/upgrade_tapes.py --shows --apply # also upgrade shows.json full-show tapes
"""
import argparse

import flb


def plan_songs(songs, runners=True):
    swaps, held = [], []
    for song in songs:
        if song.get('kind') == 'sequence':
            continue
        for slot, pick in flb.picks(song, runners):
            cur = pick.get('identifier')
            if not (cur and pick.get('audio') and pick.get('date')):
                continue
            uploads = sorted(flb.uploads_for_date(pick['date']), key=flb.rank_key)
            better = [u for u in uploads if u['identifier'] != cur and flb.is_upgrade(cur, u['identifier'])]
            for u in better[:6]:
                track = flb.find_track(u['identifier'], flb.song_names(song))
                if not track:
                    continue
                cd, nd = flb.secs(pick.get('duration', '0')), flb.secs(track['length'])
                row = {'song': song['name'], 'slot': slot, 'date': pick['date'], 'cur': cur,
                       'new': u['identifier'], 'track': track, 'rating': u, 'was': pick.get('duration')}
                if cd and abs(nd - cd) / cd > 0.30:
                    held.append({**row, 'why': f"length {pick.get('duration')} vs {track['length']}"})
                else:
                    swaps.append(row)
                break
    return swaps, held


def apply_songs(songs, swaps):
    by_name = {s['name']: s for s in songs}
    for row in swaps:
        song = by_name[row['song']]
        pick = dict(flb.picks(song))[row['slot']]
        flb.set_pick_tape(pick, row['new'], row['track'], row['rating'])


def plan_shows(shows):
    swaps = []
    for show in shows:
        cur = show['id']
        uploads = sorted(flb.uploads_for_date(show['d']), key=flb.rank_key)
        cur_files = len(flb.mp3s(cur)) or 1
        for u in uploads:
            new = u['identifier']
            if new == cur or not flb.is_upgrade(cur, new):
                continue
            if len(flb.mp3s(new)) >= 0.8 * cur_files:  # skip partial uploads
                swaps.append((show, new))
            break
    return swaps


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='write the changes')
    ap.add_argument('--no-runners', action='store_true', help='skip Best runners-up')
    ap.add_argument('--shows', action='store_true', help='also upgrade shows.json')
    args = ap.parse_args()

    songs = flb.load_songs()
    swaps, held = plan_songs(songs, runners=not args.no_runners)
    for r in swaps:
        print(f"SWAP  {r['song']} [{r['slot']}] {r['date']}: {r['cur']} -> {r['new']} "
              f"({r['track']['title']}, {r['was']} -> {r['track']['length']})")
    for r in held:
        print(f"HELD  {r['song']} [{r['slot']}] {r['date']}: {r['why']} — {r['new']}")
    print(f'\n{len(swaps)} song swaps, {len(held)} held for a listen')

    show_swaps = []
    if args.shows:
        shows = flb.load_shows()
        show_swaps = plan_shows(shows)
        for show, new in show_swaps:
            print(f"SHOW  {show['d']} {show['v']}: {show['id']} -> {new}")
        print(f'{len(show_swaps)} show swaps')

    if not args.apply:
        print('\nDry run. Re-run with --apply to write changes.')
        return
    if swaps:
        apply_songs(songs, swaps)
        flb.save_songs(songs)
        flb.bump_data_version('songs.json')
    if show_swaps:
        for show, new in show_swaps:
            show['id'] = new
        flb.save_shows(shows)
        flb.bump_data_version('shows.json')
    print('Applied. Run tools/build_tapes.py and tools/check_audio.py next.')


if __name__ == '__main__':
    main()
