"""Add songwriting credits and first release to songs.json from the Grateful Dead Family Discography
(deaddisc.com), and report songs it can't match so a person can check them.

    python3 tools/fetch_credits.py            # dry run
    python3 tools/fetch_credits.py --apply

Each song gets {"credits": {"writers": "...", "release": "Album, Year", "source": url}}. A song is
only filled from a page whose title matches one of its names; nothing is guessed.
"""
import argparse
import html
import re
import time

import flb
from fetch_setlists import title_key

DD = 'https://www.deaddisc.com/'
ROW = re.compile(r'<a href="(songs/[^"]+\.htm)"><img[^>]*></a>\s*([^<]+?)\s*<br>', re.I)
# Titles deaddisc files under another name: our name -> theirs
SAME = {'Help on the Way': 'Help On The Way', 'Slipknot!': 'Slipknot', "Walkin' Blues": 'Walkin Blues',
        'The Mighty Quinn': 'Quinn The Eskimo', 'Tons Of Steel': 'Tons Of Steel', 'King Bee': "I'm A King Bee",
        'Satisfaction': "(I Can't Get No) Satisfaction", 'Casey Jones': 'Casey Jones (Grateful Dead song)',
        'Mississippi Half-Step': 'Mississippi Half-Step Uptown Toodeloo'}


def cached(name, url):
    path = flb.CACHE / 'deaddisc' / name
    if path.exists():
        return path.read_text()
    text = flb.http_get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    time.sleep(1)  # be gentle with deaddisc.com
    return text


def index():
    page = cached('index.html', DD + 'GDFD_Songs_Perf.htm')
    out = {}
    for href, title in ROW.findall(page):
        out.setdefault(title_key(html.unescape(title)), (DD + href, html.unescape(title)))
    return out


def text(page):
    t = re.sub(r'<[^>]+>', '\n', page)
    return [html.unescape(' '.join(x.split())) for x in t.split('\n') if x.strip()]


def parse(page):
    lines = text(page)
    writers = next((re.sub(r'^Composers?:\s*', '', x) for x in lines if re.match(r'Composers?:', x)), '')
    if not writers:
        i = next((i for i, x in enumerate(lines) if re.match(r'Composers?:?$', x)), None)
        writers = lines[i + 1] if i is not None and i + 1 < len(lines) else ''
    # Releases are listed oldest first, each as "Album, Year" or "Album, Various Artists, Year"
    release = ''
    start = next((i for i, x in enumerate(lines) if x in ('Grateful Dead', 'Grateful Dead:')), None)
    if start is not None:
        for x in lines[start + 1:start + 6]:
            m = re.match(r'(.+?),\s*(?:[A-Za-z]+\s)?(\d{4})$', x)
            if m and not re.search(r'Various Artists|\((video|DVD|USB)\)', x):
                album = re.sub(r',\s*Grateful Dead$', '', m.group(1).strip())
                release = f'{album}, {m.group(2)}'
                break
    return writers.strip(' .:'), release


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    idx = index()
    songs = flb.load_songs()
    missing = []
    for s in songs:
        if s.get('kind') == 'sequence':
            continue
        names = flb.song_names(s) + ([SAME[s['name']]] if s['name'] in SAME else [])
        hit = next((idx[title_key(n)] for n in names if title_key(n) in idx), None)
        if not hit:
            missing.append(s['name'])
            continue
        url, title = hit
        writers, release = parse(cached(url.rsplit('/', 1)[1], url))
        if not writers:
            missing.append(f"{s['name']} (no composer on {url})")
            continue
        s['credits'] = {'writers': writers, **({'release': release} if release else {}), 'source': url}
        print(f"{s['name']}: {writers}" + (f' · {release}' if release else ''))
    print(f'\nNo match: {len(missing)}', missing)
    if args.apply:
        flb.save_songs(songs)
        flb.bump_data_version('songs.json')
        print('Applied.')
    else:
        print('Dry run. Re-run with --apply.')


if __name__ == '__main__':
    main()
