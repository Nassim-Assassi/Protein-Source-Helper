# Protein Source Helper

Protein Source Helper is a planned public dashboard for comparing protein-rich
grocery products across major UK supermarkets. It is intended to help shoppers
find products that fit their budget and compare their protein and other
nutrition values on a consistent basis.

The MVP will focus on a limited set of protein-relevant grocery categories and
two or three retailers, starting with Morrisons. The target refresh cadence is
daily. The implementation plan and milestones are in
[`PROJECT_PLAN.md`](./PROJECT_PLAN.md).

## Planned features

- Search products by name or brand.
- Filter by supermarket, category, protein density, and price.
- Compare product price, package size, nutrition, and value metrics.
- Sort for lowest price, protein per 100 g, or protein per pound.
- Browse best-value options and, as history accumulates, price trends.
- Show the latest successful data refresh, latest attempt status, and tracked
  retailer coverage.

## MVP product scope

The initial catalog will prioritize foods and drinks with useful protein
content, including chicken, fish, mince, Greek yogurt, cottage cheese, eggs,
tofu, beans and pulses, protein drinks and bars, and selected high-protein
ready meals or snacks. The goal is useful comparisons, not a complete catalog
of every grocery product.

## Planned architecture

1. Python scraper adapters fetch publicly available product information with
   modest request rates.
2. A shared normalization layer converts retailer-specific product data into a
   common schema.
3. Scrape results are validated and upserted to PostgreSQL.
4. GitHub Actions runs scheduled daily scrapes and records their outcomes.
5. A Streamlit dashboard reads the public catalog and presents comparisons.

Retailer-specific extraction will remain isolated behind adapters so that
changes to one supermarket site do not require rewriting the whole pipeline.
The target initial retailer set is Morrisons, Sainsbury's, and either Tesco or
Asda; the final third retailer remains to be selected.

## Data and comparison conventions

The database, including its materialized view and dashboard view, is defined
in [`database/schema.sql`](./database/schema.sql). It creates retailers,
retailer-scoped categories, brands, canonical products, retailer listings,
scrape batches, retailer-specific scrape runs, and snapshots. One batch ID
groups retailer runs launched together. Each snapshot combines one retailer
listing's price and nutrition data collected in a single run. Primary key IDs
use incrementing identity values: `snapshot_id` is `bigint`, and all other IDs
are `int`. A retailer listing refers to its retailer and canonical product,
and may refer to a category from that retailer's taxonomy. Listing identity is
retailer-specific: the retailer and external listing ID are unique when the
ID is present; when it is absent, the retailer and source URL are unique.

- Normalize nutrition values in the ETL before inserting snapshots. Store
  values per 100 g, per 100 ml, or per item, and record the basis in
  `snapshot_nutrition_basis`. Convert per-serving values only when the serving
  quantity and unit allow a reliable conversion; otherwise leave nutrition
  values unknown. Do not convert between grams and millilitres without a
  reliable density.
- Every snapshot must include energy and protein values on its stated
  nutrition basis. The database rejects snapshots missing either value; other
  nutrient fields may remain unknown.
- Every snapshot must include a positive package quantity and its unit (`g`,
  `ml`, or `each`). The base tables do not store derived comparison metrics;
  `current_data_mat` calculates price per 100 package units and total protein
  grams per currency unit. Price per 100 package units can represent different
  physical units and must not be compared across unlike units.
- A snapshot row combines price and nutrition data and is unique per retailer
  listing per scrape run. Ingestion should upsert on
  `(retailer_listing_id, scrape_run_id)`; run timestamps provide the collection
  window for its snapshots.
- `current_data_mat` contains in-stock snapshots from each retailer's most
  recent successful run, provided that run finished within the last 26 hours.
  It does not fall back to an older snapshot for a listing omitted from that
  run. Running or failed attempts do not replace the latest successful data;
  show run status separately if the dashboard needs to communicate a newer
  attempt's progress or failure. Only active retailers and listings are
  included. `current_data` selects from this materialized view and checks the
  26-hour freshness window at query time, so expired rows are hidden even
  between refreshes.
- Missing products are not recorded as snapshots. A product is marked inactive
  only after it is absent from two consecutive successful retailer runs;
  failed runs do not count. A product omitted from the latest successful run
  is absent from `current_data_mat` immediately, even before it is marked
  inactive.
  Missing optional nutrient values remain unknown rather than being treated
  as zero.
- Comparisons must avoid calculating metrics when required inputs are missing.
- Protein per pound should use protein per 100 g and price per 100 g, or
  equivalent package-level values, with consistent units.

## Repository contents

- [`database/schema.sql`](./database/schema.sql) — full database definition:
  tables, constraints, indexes, `current_data_mat`, and `current_data`.
- [`database/initial_database_setup.sh`](./database/initial_database_setup.sh)
  — applies the full schema using the database settings in the project-root
  `.env` file. This is a destructive reset that drops existing tables and
  dependent objects; the SQL runs in one transaction so failures roll back.
- [`database/refresh_materialised_view.sh`](./database/refresh_materialised_view.sh)
  — refreshes `current_data_mat` concurrently using the same `.env` settings.
- [`database/refresh_materialised_view.sql`](./database/refresh_materialised_view.sql)
  — contains the concurrent refresh statement.
- [`morrisons_mvp_links.txt`](./morrisons_mvp_links.txt) —
  Morrisons product links for initial exploration.
- [`morrisons_product_categories.csv`](./morrisons_product_categories.csv) —
  product and category URL data for initial exploration.
- [`requirements.txt`](./requirements.txt) — current Python dependencies.
- [`local_development/`](./local_development/) — local development files.

The repository currently contains the schema and Morrisons research inputs.
The scrapers, ingestion pipeline, deployed dashboard, and scheduled automation
are planned work, not yet described here as completed features.

## Getting started

The database scripts require `psql` and a project-root `.env` file containing
shell-compatible assignments for `DATABASE_HOST`, `DATABASE_PORT`,
`DATABASE_NAME`, `DATABASE_USER`, and `DATABASE_PASSWORD`. Keep this file
private and do not commit database credentials.

1. Create a PostgreSQL database and configure the required values in `.env`.
2. Initialize the database by running
  `sh database/initial_database_setup.sh` from the project root. This drops
  existing application tables and dependent objects before recreating the
  schema, so do not run it to refresh data or against data you need to keep.
3. After loading or updating snapshots, refresh the materialized data by
  running `sh database/refresh_materialised_view.sh`. The dashboard should
  query `public.current_data`; its 26-hour filter is evaluated on each query.

Refresh scheduling is planned for the scraper logic and is not yet automated
by these database scripts.

Configure separate database credentials and least-privilege permissions for
the scraper and dashboard on the selected provider. Keep credentials in a
trusted environment, such as GitHub Actions secrets, and never expose write
credentials in the public Streamlit application. The current Python
dependencies are listed in
[`requirements.txt`](./requirements.txt).

## Responsible data collection

Before scraping a retailer, review its terms and any applicable access rules.
Do not access account-only or personal data. Keep request rates modest, avoid
unnecessary repeat requests, and record source URLs and scrape timestamps.
Retailer page changes and incomplete nutrition data are expected failure
modes; the project plan includes validation and monitoring work to handle them.

## Project status

This is an early MVP foundation. Use [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) for
the implementation sequence, validation criteria, and risks.
