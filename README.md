# Protein Source Helper

Protein Source Helper collects public grocery product data and publishes a
read-only static dashboard comparing protein value across UK retailers.
The current implementation scrapes Morrisons products, stores validated
snapshots in PostgreSQL, and deploys fresh dashboard data to GitHub Pages.

## Live dashboard

- [Open the live GitHub Pages dashboard](https://nassim-assassi.github.io/Protein-Source-Helper/)
- [View workflow runs and deployment status](https://github.com/Nassim-Assassi/Protein-Source-Helper/actions)

GitHub Pages is rebuilt when dashboard files or the Pages workflow change, or
after a successful `Scrapers Batch Workflow` run. The batch workflow is also
available for manual dispatch.

## Current features

- Morrisons product discovery and extraction across retailer categories.
- Shared extract, transform, and load pipeline with validation and structured
  scrape-run metrics.
- PostgreSQL schema for retailers, categories, brands, listings, batches,
  runs, and historical snapshots.
- Freshness-filtered data views and derived cost, protein, ranking, and value
  metrics.
- Static browser dashboard with retailer coverage, data-quality KPIs, and
  balanced, cost-saving, and protein-focused rankings.
- GitHub Actions workflows for batch scraping, GitHub Pages publication,
  integration tests, Python tests and linting, and SQL linting.
- Local CSV export mode for testing a retailer extraction without database writes.

## Usage

### Prerequisites

- Python 3.14
- PostgreSQL and `psql`
- Database credentials
- Chromium for Playwright-based Morrisons extraction

### Install dependencies

```sh
python -m pip install -r requirements-dev.txt
python -m pip install -r scrapers/requirements.txt
python -m playwright install --with-deps chromium
```

### Configure the database

Set `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, and
`DATABASE_PASSWORD` in a project-root `.env` file or environment. Never commit
this file or credentials.

Create a fresh database schema:

```sh
sh database/initial_database_setup.sh
```

This reset drops existing application objects in the
`protein_source_helper` schema. For an existing installation, migrate them once:

```sh
sh database/migrate_to_protein_source_helper.sh
```

Recreate views or refresh the materialized view without resetting base tables:

```sh
sh database/recreate_views.sh
sh database/refresh_materialised_view.sh
```

### Run the Morrisons ETL

The batch workflow initiates a batch and one scrape run for each retailer in the
`RETAILERS` repository variable. For a local extraction test:

```sh
python -m scrapers.orchestrators.retailer_etl \
  --retailer-name Morrisons \
  --retailer-url https://groceries.morrisons.com \
  --local_test
```

This writes transformed rows to `local_development/morrisons_products.csv`.
To load a scrape into PostgreSQL, provide a batch ID:

```sh
python -m scrapers.orchestrators.retailer_etl \
  --batch-id <BATCH_ID> \
  --retailer-name Morrisons \
  --retailer-url https://groceries.morrisons.com
```

The SQL batch scripts in `database/` initiate and finalise scrape batches.

### Preview the static dashboard

Generate dashboard JSON:

```sh
python -m pip install -r static_summary_pages/requirements.txt
python static_summary_pages/summary_pages_generator.py
```

Serve the repository root and open the static pages:

```sh
python3 -m http.server 4173
```

Visit `http://localhost:4173/static_summary_pages/`.

The browser loads `static_summary_pages/data/dashboard-data.json`; it does not
connect directly to PostgreSQL or receive database credentials.

### Run tests

```sh
pytest
```

Lint and test workflows are included in `.github/workflows/`.

## Repository layout

- [`database/`](./database/) - PostgreSQL schema, views, migrations, and batch scripts.
- [`scrapers/`](./scrapers/) - extraction, transformation, loading, orchestration,
  and scraper tests.
- [`static_summary_pages/`](./static_summary_pages/) - browser dashboard and
  PostgreSQL JSON exporter.
- [`local_development/`](./local_development/) - local test inputs and generated CSVs.
- [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) - remaining planned work and future scope.

## Data conventions

The database stores package quantity and unit, energy and protein on an
explicit nutrition basis, optional nutrient values, and per-run scrape results.
The dashboard reads `protein_source_helper.current_data`, which hides stale and
out-of-stock listings. Derived metrics are not displayed when required values
are missing or units are incompatible.

## Responsible collection

Review retailer terms and applicable access rules before scraping. Collect only
public product information, use modest request rates, and keep account data and
credentials out of the project and browser output.
