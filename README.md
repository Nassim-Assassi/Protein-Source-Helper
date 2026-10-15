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

The initial database schema is in [`database/schema.sql`](./database/schema.sql).
It defines retailers, brands, categories, products, product snapshots, and
scrape batches with retailer-specific run records. One batch ID groups the
individual retailer runs launched together. Each snapshot combines one
product's price and nutrition data collected in a single run. Primary key IDs
use incrementing identity values: `snapshot_id` is `bigint`, and all other IDs
are `int`. Foreign key columns use the same type as the referenced ID. Products
refer to a retailer and optionally to normalized brand and category records.
Product identity is retailer-specific, using the retailer and external product
ID when available, or the canonical product source URL when no external ID is
available.

- Normalize nutrition values in the ETL before inserting snapshots. Store
  values only per 100 g or per 100 ml, and record the basis in
  `snapshot_nutrition_basis`. Convert per-serving values only when the serving
  quantity and unit allow a reliable conversion; otherwise leave nutrition
  values unknown. Do not convert between grams and millilitres without a
  reliable density.
- Every snapshot must include energy and protein values on its stated
  nutrition basis. The database rejects snapshots missing either value; other
  nutrient fields may remain unknown.
- Package quantity and unit should be retained so unit-price calculations are
  transparent. Derived comparison metrics are calculated by the application,
  not stored as columns.
- A snapshot row combines price and nutrition data and is unique per product
  per scrape run. Ingestion should upsert on `(product_id, scrape_run_id)`;
  run timestamps provide the collection window for its snapshots.
- The `current_data` view exposes products with snapshots in each retailer's
  most recent successful run only. It never falls back to an older snapshot
  for a product omitted from that run, and includes data only when that run
  finished within the last 24 hours. A retailer with no successful run in that
  window contributes no rows. Running or failed attempts do not replace the
  latest successful data; show run status separately if the dashboard needs
  to communicate a newer attempt's progress or failure.
- Missing products are not recorded as snapshots. A product is marked inactive
  only after it is absent from two consecutive successful retailer runs;
  failed runs do not count. A product omitted from the latest successful run
  is hidden from `current_data` immediately, even before it is marked inactive.
  Missing optional nutrient or package values remain unknown rather than
  being treated as zero.
- Comparisons must avoid calculating metrics when required inputs are missing.
- Protein per pound should use protein per 100 g and price per 100 g, or
  equivalent package-level values, with consistent units.

## Repository contents

- [`database/schema.sql`](./database/schema.sql) — portable PostgreSQL tables,
  constraints, indexes, and current-data views. ETL code supplies required
  values explicitly; database roles and permissions are configured separately
  for each hosting provider.
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

The initial schema can be applied to a PostgreSQL database using `psql` or a
provider's SQL editor (including Supabase):

1. Create a PostgreSQL database.
2. Run [`database/schema.sql`](./database/schema.sql) against the database.
3. Add retailer records and configure scraper credentials for local
   development when the ingestion code is in place.

Configure separate database credentials and least-privilege permissions for
the scraper and dashboard on the selected provider. Keep credentials in a
trusted environment, such as GitHub Actions secrets, and never expose write
credentials in the public Streamlit application or commit them to the
repository. The current Python dependencies are listed in
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
