"""Shared helpers for the First Last Best data tools (stdlib only)."""
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / '.cache'
SONGS = ROOT / 'songs.json'
SHOWS = ROOT / 'shows.json'
TAPES = ROOT / 'tapes.json'
UA = {'User-Agent': 'firstlastbest-tools/1.0 (+https://firstlastbest.com)'}


# ---------- files ----------

def load_songs():
    return json.loads(SONGS.read_text())


def save_songs(data):
    SONGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def load_shows():
    return json.loads(SHOWS.read_text())


def save_shows(data):
    SHOWS.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')


def bump_version(path, asset):
    """Increment `asset?v=N` inside `path` (cache busting)."""
    p = ROOT / path
    text = p.read_text()
    pat = re.compile(re.escape(asset) + r'\?v=(\d+)')
    m = pat.search(text)
    if not m:
        raise SystemExit(f'{asset}?v= not found in {path}')
    p.write_text(pat.sub(f'{asset}?v={int(m.group(1)) + 1}', text, count=1))


def bump_data_version(asset):
    """Bump a data file version in app.js, then app.js itself in index.html."""
    bump_version('app.js', asset)
    bump_version('index.html', 'app.js')


# ---------- network ----------

def http_get(url, retries=3, timeout=60):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def _cached_json(kind, key, url, refresh=False):
    path = CACHE / kind / (re.sub(r'[^A-Za-z0-9._-]', '_', key) + '.json')
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = json.loads(http_get(url))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def metadata(ident, refresh=False):
    """archive.org item metadata (files, metadata, reviews)."""
    return _cached_json('meta', ident, f'https://archive.org/metadata/{ident}', refresh)


def uploads_for_date(date, refresh=False):
    """All Grateful Dead uploads for YYYY-MM-DD with rating and review count."""
    q = urllib.parse.quote(f'collection:GratefulDead AND date:{date}')
    url = (f'https://archive.org/advancedsearch.php?q={q}&fl[]=identifier&fl[]=avg_rating'
           f'&fl[]=num_reviews&rows=100&output=json')
    return _cached_json('uploads', date, url, refresh)['response']['docs']


def audio_ok(url):
    """True if the file answers a ranged GET with 200/206."""
    req = urllib.request.Request(url, headers={**UA, 'Range': 'bytes=0-1023'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status in (200, 206)
    except Exception:
        return False


# ---------- recordings ----------

SBD, MATRIX, AUD, UNKNOWN = 0, 1, 2, 3
SOURCE_NAMES = {SBD: 'Soundboard', MATRIX: 'Matrix', AUD: 'Audience', UNKNOWN: 'Unknown'}


def source_class(ident):
    """Best-guess recording type from an archive.org identifier."""
    i = ident.lower()
    if re.search(r'matrix|mtx', i):
        return MATRIX
    if re.search(r'(^|[.\-_])d?sbd([.\-_]|$)|soundboard|betty', i):
        return SBD
    if re.search(r'(^|[.\-_])(aud|fob|ots)([.\-_]|$)|akg|nak|senn|schoeps|neumann|beyer|sony|pzm|dak|ecm', i):
        return AUD
    return UNKNOWN


def is_miller(ident):
    return 'miller' in ident.lower()


def risky_source(ident):
    """Tapes we never auto-pick: monitor mixes and half-aud/half-sbd uploads."""
    i = ident.lower()
    return 'monitor' in i or ('aud' in i and 'sbd' in i)


def rank_key(doc):
    """Sort uploads best-first: soundboard > matrix > audience, Miller first, then reviews."""
    ident = doc['identifier']
    return (source_class(ident), 0 if is_miller(ident) else 1, -(doc.get('num_reviews') or 0))


def is_upgrade(cur, new):
    """Would `new` be a better recording than `cur`? Never a step down."""
    c, n = source_class(cur), source_class(new)
    if risky_source(new) or (c == UNKNOWN and n >= AUD):
        return False
    if n < c:
        return True
    return n == c and is_miller(new) and not is_miller(cur)


# ---------- track matching ----------

def norm_title(t, drop_paren=False):
    t = (t or '').lower().replace('&', 'and')
    t = re.sub(r'\.(mp3|flac|shn)$', '', t)
    t = re.sub(r'^\s*(gd\d{2,4}-\d\d-\d\d)?\s*(d\d+)?(s\d+)?t?\d+[\s.\-_]*', '', t)
    t = re.sub(r'^\s*(e|encore)\s*:\s*', '', t)
    if drop_paren:
        t = re.sub(r'\(.*?\)', '', t)
    t = re.sub(r'\bsaint\b', 'st', t)
    t = re.sub(r"in['’]?g?\b", 'in', t)
    return re.sub(r'[^a-z0-9]', '', t)


def title_keys(names):
    keys = set()
    for n in names:
        keys.add(norm_title(n))
        keys.add(norm_title(n, True))
    return {k for k in keys if len(k) >= 3}


def secs(x):
    try:
        parts = [float(v) for v in str(x).split(':')]
        return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
    except ValueError:
        return 0


def mmss(s):
    s = int(round(s))
    return f'{s // 60:02d}:{s % 60:02d}'


def mp3s(ident):
    return [f for f in metadata(ident).get('files', []) if f.get('format') == 'VBR MP3']


def find_track(ident, names):
    """The song's MP3 in an upload, matched on title or filename (longest if it repeats)."""
    keys = title_keys(names)
    hits = [f for f in mp3s(ident)
            if any(t and (norm_title(t) in keys or norm_title(t, True) in keys)
                   for t in (f.get('title'), f['name']))]
    if not hits:
        return None
    f = max(hits, key=lambda f: secs(f.get('length', '0')))
    return {'name': f['name'], 'title': f.get('title') or re.sub(r'\.mp3$', '', f['name']),
            'length': mmss(secs(f.get('length', '0')))}


def audio_url(ident, filename):
    return f'https://archive.org/download/{ident}/' + urllib.parse.quote(filename, safe="'")


def song_names(song):
    return [song['name']] + song.get('aliases', [])


def picks(song, runners=True):
    """(slot, pick) for First/Last/Best and, optionally, Best runners-up."""
    out = [(k, song.get(k)) for k in ('first', 'last', 'best') if song.get(k)]
    if runners:
        out += [(f'runnerUp{i + 1}', r) for i, r in enumerate((song.get('best') or {}).get('runnersUp', []))]
    return out


def set_pick_tape(pick, ident, track, rating=None):
    """Point a single-track pick at a new upload, keeping the card fields consistent."""
    pick['audio'] = audio_url(ident, track['name'])
    pick['track'] = track['title']
    pick['duration'] = track['length']
    if 'combined' in pick:
        pick['combined'] = track['title'].rstrip().endswith('>')
    pick['identifier'] = ident
    pick['recording'] = f'https://archive.org/details/{ident}'
    if 'rating' in pick or 'reviews' in pick:
        if rating and rating.get('avg_rating') is not None:
            pick['rating'] = rating['avg_rating']
            pick['reviews'] = rating.get('num_reviews') or 0
        else:
            pick.pop('rating', None)
            pick.pop('reviews', None)


def clean_text(v):
    if v is None:
        return ''
    if isinstance(v, list):
        v = ' | '.join(str(x) for x in v)
    v = html.unescape(re.sub(r'<br\s*/?>', '\n', str(v), flags=re.I))
    return re.sub(r'<[^>]+>', ' ', v)
