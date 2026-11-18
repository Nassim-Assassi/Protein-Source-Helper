# Static summary pages

This directory contains the initial read-only Protein Source Helper static summary pages.

## Regenerate data

Run from the project root:

```sh
.venv/bin/python static_summary_pages/summary_pages_generator.py
```

The exporter reads `protein_source_helper.current_data` and writes
`static_summary_pages/data/dashboard-data.json`. It uses the database-derived metrics and
filters to in-stock, active listings.

## Preview

Serve the project directory with a local static server:

```sh
python3 -m http.server 4173
```

Then open `http://localhost:4173/static_summary_pages/`.

The JSON payload is separate from the browser code so it can later be replaced
by an API endpoint. The dashboard has no database credentials or live database
connection.

## GitHub Pages hosting

GitHub Pages only serves the generated files in `static_summary_pages/`. The
page makes no database request: it loads `data/dashboard-data.json` and runs
entirely in the browser.

1. Run the exporter while the database is available.
2. Commit the updated files under `static_summary_pages/`.
3. Push to `main`.
4. In **Settings > Pages**, set **Source** to **GitHub Actions**.

The included Pages workflow publishes `static_summary_pages/` as the site root
and can also be started manually from **Actions**.

Database credentials are needed only while running the exporter. They must remain
as local environment variables or GitHub Actions secrets and must never be
included in JSON or browser code.
