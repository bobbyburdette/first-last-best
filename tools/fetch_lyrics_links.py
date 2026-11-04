"""Link each song to its lyrics on dead.net, the band's official site.

    python3 tools/fetch_lyrics_links.py            # dry run
    python3 tools/fetch_lyrics_links.py --apply

Reads the dead.net song index, matches titles to songs.json, then opens each matched page and only keeps
the link when that page actually shows lyrics. Adds {"lyrics": url} to the song. Gentle: one request
every 2 seconds, cached in tools/.cache/deadnet/.
"""
import argparse
import html
import re
import time

import flb
from fetch_setlists import title_key

BASE = 'https://www.dead.net'
LINK = re.compile(r'<a href="(/song/[a-z0-9-]+)" hreflang="en">([^<]+)</a>')
# Pages the index misses or files under another title: our name -> dead.net path (still checked for lyrics)
EXTRA = {'Let It Grow': '/song/weather-report-suite-part-ii-let-it-grow',
         'Mississippi Half-Step': '/song/mississippi-half-step-uptown-toodleloo', 'Mr. Charlie': '/song/mister-charlie',
         "Just Like Tom Thumb's Blues": '/song/just-tom-thumb-blues', 'Day Job': '/song/keep-your-day-job',
         'Two Souls In Communion': '/song/stranger-two-souls-communion', 'China Doll': '/song/china-doll',
         'Cosmic Charlie': '/song/cosmic-charlie', 'Stuck Inside Of Mobile': '/song/stuck-inside-mobile-memphis-blues-again'}
LYRICS = re.compile(r'field--name-field-lyrics\s.*?<div class="field__item">(.*?)</div>', re.S)


def get(path):
    f = flb.CACHE / 'deadnet' / (re.sub(r'[^A-Za-z0-9]', '_', path) + '.html')
    if f.exists():
        return f.read_text()
    try:
        text = flb.http_get(BASE + path)
    except Exception:
        text = ''  # a missing page just means no link
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    time.sleep(2)  # be gentle with dead.net
    return text


def index():
    out, page = {}, 0
    while True:
        found = LINK.findall(get(f'/songs?page={page}' if page else '/songs'))
        new = [(h, t) for h, t in found if h not in out.values()]
        if not new:
            return out
        for href, title in new:
            title = html.unescape(title)
            for key in {title_key(title), title_key(re.sub(r'\s*\(.*?\)', '', title))}:
                out.setdefault(key, href)
        page += 1


def has_lyrics(page):
    m = LYRICS.search(page)
    return bool(m) and len(re.sub(r'<[^>]+>|\s', '', m.group(1))) > 80


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    idx = index()
    print(f'{len(set(idx.values()))} songs on dead.net')
    songs = flb.load_songs()
    linked, missing = 0, []
    for s in songs:
        if s.get('kind') == 'sequence':
            continue
        href = EXTRA.get(s['name']) or next((idx[k] for n in flb.song_names(s) for k in (title_key(n), title_key(re.sub(r'\s*\(.*?\)', '', n)))
                     if k in idx), None)
        if not href or not has_lyrics(get(href)):
            s.pop('lyrics', None)
            missing.append(s['name'] + ('' if not href else ' (no lyrics on page)'))
            continue
        s['lyrics'] = BASE + href
        linked += 1
    print(f'Linked {linked}. No lyrics found for {len(missing)}:', missing)
    if args.apply:
        flb.save_songs(songs)
        flb.bump_data_version('songs.json')
        print('Applied.')
    else:
        print('Dry run. Re-run with --apply.')


if __name__ == '__main__':
    main()
