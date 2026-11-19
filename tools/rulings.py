"""Apply data/rulings.json and JerryBase's concert marks to setlists.

    show_status(date, entry)  -> (counts: bool, reason: str)  for a whole show
    play_status(entry, row)   -> 'unconfirmed' | ''           for one song in a counted show
"""
import json

import flb

RULINGS = flb.ROOT / 'data' / 'rulings.json'


def load():
    return json.loads(RULINGS.read_text()) if RULINGS.exists() else {'shows': {}, 'songs': {}}


R = load()


def show_rule(date):
    return R.get('shows', {}).get(date) or {}


def song_rule(name):
    return R.get('songs', {}).get(name) or {}


def no_tape_listing(entry):
    """A SetList Program setlist with no tape: what it lists can't be checked, so it's shown as unconfirmed."""
    return entry.get('source') == 'setlistprogram' and not entry.get('id')


def show_status(date, entry):
    """Whether a show's setlist counts toward histories, play counts, First/Last and This Day."""
    rule = show_rule(date)
    if 'counts' in rule:
        return bool(rule['counts']), rule.get('reason', '')
    if rule.get('setlist') == 'ignore':
        return False, rule.get('reason', '')
    if entry.get('notConcert') and not no_tape_listing(entry):
        return False, entry['notConcert']
    return True, ''


def play_status(entry, row, key):
    """'unconfirmed': only The SetList Program lists the song that night and no tape has it. JerryBase wins."""
    if entry.get('source') != 'setlistprogram' or key in (entry.get('jbSongs') or []):
        return ''
    return 'unconfirmed' if (not entry.get('id') or row[1] < 0) else ''


def counted_setlists(setlists):
    return {d: e for d, e in setlists.items() if show_status(d, e)[0]}
