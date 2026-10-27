# Data tools

Scripts that maintain `songs.json`, `shows.json` and `tapes.json`. Python 3, standard library only. Run from the repo root. archive.org lookups are cached in `tools/.cache/` (not committed).

| Script | What it does |
|---|---|
| `upgrade_tapes.py` | Moves picks to a better recording of the same show: Miller soundboard > soundboard > matrix > audience. Never a step down; skips length mismatches, monitor mixes and half-aud/half-sbd tapes and lists them for a listen. `--shows` does the same for Shows on this day. |
| `refresh_runnersup.py` | Updates Best vote counts and the two runners-up from HeadyVersion. Reports, but doesn't change, songs whose #1 has moved. |
| `build_tapes.py` | Rebuilds `tapes.json` (tape notes on the cards) from archive.org metadata. |
| `check_audio.py` | Confirms every audio file still plays. |
| `build_pages.py` | Writes a crawlable page for every song (`/song/<slug>/`) and show (`/show/<date>/`), plus `sitemap.xml` and `404.html`, from `index.html`. Run after any change to `index.html`, `app.js`, `style.css`, `songs.json` or `shows.json`. `--check` reports stale pages. |
| `indexnow.py` | After a change is live, tells Bing and other IndexNow engines which pages changed. |

Every script is a dry run unless you pass `--apply` (except `build_tapes.py`, `check_audio.py` and `build_pages.py`, which are safe to run). Writing a data file also bumps its `?v=` cache-busting number in `app.js` and `index.html`.

Typical refresh:

```
python3 tools/refresh_runnersup.py --apply
python3 tools/upgrade_tapes.py --apply
python3 tools/build_tapes.py
python3 tools/check_audio.py
python3 tools/build_pages.py
# commit, push, wait for the site to update, then:
python3 tools/indexnow.py
```
