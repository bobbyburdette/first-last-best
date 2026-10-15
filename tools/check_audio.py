"""Check that every audio file the site plays still answers. archive.org servers are flaky,
so failures are retried before being reported.

    python3 tools/check_audio.py            # all songs (First/Last/Best, runners-up, sequences)
    python3 tools/check_audio.py --limit 50 # quick spot check
"""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor

import flb


def urls(songs):
    out = set()
    for song in songs:
        for _, pick in flb.picks(song):
            if pick.get('audio'):
                out.add(pick['audio'])
            for t in pick.get('tracks', []):
                out.add(t['url'])
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()
    todo = urls(flb.load_songs())
    if args.limit:
        todo = todo[:args.limit]
    with ThreadPoolExecutor(12) as pool:
        bad = [u for u, ok in zip(todo, pool.map(flb.audio_ok, todo)) if not ok]
    for attempt in range(2):
        if not bad:
            break
        time.sleep(5)
        bad = [u for u in bad if not flb.audio_ok(u)]
    print(f'{len(todo)} checked, {len(bad)} failing')
    for u in bad:
        print('  ', u)


if __name__ == '__main__':
    main()
