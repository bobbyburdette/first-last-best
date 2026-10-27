"""Tell Bing (and other IndexNow search engines) which pages changed, so they recrawl now.

    python3 tools/indexnow.py                 # pages changed in the last commit
    python3 tools/indexnow.py --since HEAD~5  # pages changed since a commit
    python3 tools/indexnow.py --all           # every URL in sitemap.xml

Run it after the change is live on firstlastbest.com. The key file in the site root proves
ownership; it is public by design.
"""
import argparse
import json
import re
import subprocess
import urllib.request

import flb

SITE = 'https://firstlastbest.com'


def key():
    keys = [p.stem for p in flb.ROOT.glob('*.txt') if re.fullmatch(r'[0-9a-f]{32}', p.stem)]
    if len(keys) != 1:
        raise SystemExit('expected exactly one IndexNow key file (32 hex chars + .txt) in the site root')
    return keys[0]


def changed_urls(since):
    out = subprocess.run(['git', 'diff', '--name-only', since, 'HEAD'], cwd=flb.ROOT, capture_output=True, text=True, check=True).stdout
    urls = set()
    for f in out.split():
        if f == 'index.html':
            urls.add('/')
        elif re.fullmatch(r'(song|show|this-day)/.*index\.html', f):
            urls.add('/' + f[:-len('index.html')])
    return sorted(urls)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--since', default='HEAD~1')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()
    paths = (re.findall(rf'<loc>{re.escape(SITE)}(/[^<]*)</loc>', (flb.ROOT / 'sitemap.xml').read_text())
             if args.all else changed_urls(args.since))
    if not paths:
        print('nothing to submit')
        return
    k = key()
    for i in range(0, len(paths), 10000):
        body = json.dumps({'host': 'firstlastbest.com', 'key': k, 'keyLocation': f'{SITE}/{k}.txt',
                           'urlList': [SITE + p for p in paths[i:i + 10000]]}).encode()
        req = urllib.request.Request('https://api.indexnow.org/indexnow', data=body,
                                     headers={'Content-Type': 'application/json; charset=utf-8'})
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f'submitted {len(paths[i:i + 10000])} URLs: HTTP {r.status}')


if __name__ == '__main__':
    main()
