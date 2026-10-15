"""Rebuild tapes.json: recording type, taper, transferer, lineage and a short note for every
First/Last/Best tape, taken from archive.org metadata.

    python3 tools/build_tapes.py   # writes tapes.json and bumps its version in app.js
"""
import json
import re

import flb

SKIP = re.compile(r'^(notes?:?|comments?:?|source:|lineage:|transfer|taper|set ?\d|disc ?\d|d\d+t\d+|\d+[.)-]|'
                  r'e:|encore|-+$|=+$|md5|ffp|shn|flac|checksum|https?://|this (show|recording) is part|setlist)', re.I)


def oneline(v):
    return ' '.join(flb.clean_text(v).split())


def kind(source, ident):
    if re.search(r'(^|[.\-_])(pre-)?fm([.\-_]|$)', ident.lower()):
        return 'FM broadcast'
    c = flb.source_class(ident)
    if c != flb.UNKNOWN:
        return flb.SOURCE_NAMES[c]
    s = (source + ' ' + ident).lower()
    if re.search(r'cmc\d|mk\d|schoeps|akg|nak|senn|neumann|beyer|microphone', s):
        return 'Audience'
    if re.search(r'matrix|\bmtx\b', s):
        return 'Matrix'
    if re.search(r'\bsbd\b|soundboard|board', s):
        return 'Soundboard'
    if re.search(r'\bfm\b|broadcast|radio', s):
        return 'FM broadcast'
    if re.search(r'\baud\b|audience|\bfob\b', s):
        return 'Audience'
    return ''


def names(v, limit=2):
    v = oneline(v)
    if not v or re.search(r'unknown|see notes|n/a', v, re.I):
        return ''
    parts = [p.strip(' .;') for p in re.split(r',|;| and |/', v) if p.strip(' .;')]
    parts = [p for p in parts if len(p) < 40 and '@' not in p and not re.search(r'https?:|www\.', p)]
    if not parts:
        return ''
    return ', '.join(parts[:limit]) + (' and others' if len(parts) > limit else '')


def lineage(meta):
    for key in ('lineage', 'source'):
        v = oneline(meta.get(key))
        v = re.sub(r'(Recording|Transfer|Source)\s*Info:\s*', '', v, flags=re.I)
        v = re.sub(r'\s*(\[?Note:|Transferred and Edited By).*$', '', v, flags=re.I).strip()
        if v and not re.fullmatch(r'(see notes\.?|n/a|unknown)', v, re.I) and '>' in v:
            return v[:200] + ('…' if len(v) > 200 else '')
    return ''


def note(meta):
    raw = flb.clean_text(meta.get('notes'))
    out = []
    for line in re.split(r'\n|(?<=\.)\s{2,}| -- ', raw):
        line = ' '.join(line.strip(' -*•\t').split())
        if len(line) < 25 or SKIP.search(line):
            continue
        if re.search(r'\.(mp3|flac|shn|ffp|md5)\b|\b(d\d+t\d+|\d+:\d\d)\b', line, re.I):
            continue
        if len(re.findall(r'->|>', line)) >= 2 or re.search(r'@|https?:|recording info|transfer info', line, re.I):
            continue
        out.append(line)
        if sum(len(x) for x in out) > 140:
            break
    text = ' '.join(x if re.search(r'[.!?)]$', x) else x + '.' for x in out)
    if len(text) > 230:
        text = text[:230].rsplit(' ', 1)[0] + '…'
    text = re.sub(r'\[?\s*Note:\s*', '', text, flags=re.I).replace(']', '').strip()
    text = re.sub(r';\s*\.', '.', text)
    if re.search(r'->|\s>\s|>\s*$', text):
        return ''
    text = re.sub(r'([.!?]\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), text)
    return text[:1].upper() + text[1:]


def entry(ident):
    meta = flb.metadata(ident).get('metadata', {})
    e = {'kind': kind(oneline(meta.get('source')), ident),
         'taper': names(meta.get('taper')),
         'transfer': names(meta.get('transferer')),
         'lineage': lineage(meta),
         'note': note(meta)}
    if flb.is_miller(ident) and 'Miller' not in e['transfer']:
        e['transfer'] = 'Charlie Miller'
    e = {k: re.sub(r'\S+@\S+\.\w+', '', v).strip(' ,;') for k, v in e.items()}
    return {k: v for k, v in e.items() if v}


def main():
    ids = sorted({p['identifier'] for s in flb.load_songs()
                  for _, p in flb.picks(s, runners=False) if p.get('identifier')})
    tapes = {i: entry(i) for i in ids}
    flb.TAPES.write_text(json.dumps(tapes, ensure_ascii=False, separators=(',', ':')))
    flb.bump_data_version('tapes.json')
    print(f'tapes.json: {len(tapes)} tapes')


if __name__ == '__main__':
    main()
