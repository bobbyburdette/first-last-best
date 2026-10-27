# First Last Best

Static site on GitHub Pages (deploys from `main`, custom domain firstlastbest.com). No build system: `index.html`, `app.js`, `style.css` and JSON data files are served as-is.

- Every song and show has a real page (`/song/<slug>/`, `/show/<YYYY-MM-DD>/`, `/this-day/`) generated from `index.html` by `tools/build_pages.py`. After changing `index.html`, `app.js`, `style.css`, `songs.json` or `shows.json`, bump the `?v=` cache-busting numbers and run `python3 tools/build_pages.py`, then commit the regenerated pages with the change. Never edit files under `song/` or `show/` by hand.
- Asset paths in `index.html` and data fetches in `app.js` must stay root-absolute (`/app.js`, `/songs.json`) because pages live in subfolders.
- Data tools and the refresh routine are documented in `tools/README.md`.
