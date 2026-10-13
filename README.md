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
- Show the latest successful data refresh and tracked retailer coverage.

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
3. Scrape results are validated and upserted to Supabase Postgres.
4. GitHub Actions runs scheduled daily scrapes and records their outcomes.
5. A Streamlit dashboard reads the public catalog and presents comparisons.

Retailer-specific extraction will remain isolated behind adapters so that
changes to one supermarket site do not require rewriting the whole pipeline.
The target initial retailer set is Morrisons, Sainsbury's, and either Tesco or
Asda; the final third retailer remains to be selected.

## Data and comparison conventions

The initial database schema is in [`supabase/schema.sql`](./supabase/schema.sql).
It defines retailers, products, daily price snapshots, daily nutrition
snapshots, and scraper run records. Primary keys use incrementing `bigint`
identity values, with `bigint` foreign keys referencing them. Product identity
is retailer-specific, using the retailer and external product ID when
available.

- Nutrition values should be normalized to per 100 g where the source data
  permits.
- Package quantity and unit should be retained so unit-price calculations are
  transparent. The schema calculates `price_per_100g` for gram-based package
  sizes.
- Price and nutrition snapshots are unique per product and UTC calendar day;
  ingestion should upsert on `(product_id, snapshot_date)`.
- Comparisons must distinguish unavailable values from zero and avoid
  calculating metrics when required inputs are missing.
- Protein per pound should use protein per 100 g and price per 100 g, or
  equivalent package-level values, with consistent units.

## Repository contents

- [`supabase/schema.sql`](./supabase/schema.sql) — initial Supabase tables,
  constraints, indexes, update trigger, and public read policies.
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

The initial schema can be applied in the Supabase SQL Editor:

1. Create a Supabase project.
2. Run [`supabase/schema.sql`](./supabase/schema.sql) in the SQL Editor.
3. Add retailer records and configure scraper credentials for local
   development when the ingestion code is in place.

Scraper writes should use a Supabase service-role key kept in a trusted
environment, such as GitHub Actions secrets. Never expose that key in the
public Streamlit application or commit it to the repository. The current
Python dependencies are listed in [`requirements.txt`](./requirements.txt).

## Responsible data collection

Before scraping a retailer, review its terms and any applicable access rules.
Do not access account-only or personal data. Keep request rates modest, avoid
unnecessary repeat requests, and record source URLs and scrape timestamps.
Retailer page changes and incomplete nutrition data are expected failure
modes; the project plan includes validation and monitoring work to handle them.

## Project status

This is an early MVP foundation. Use [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) for
the implementation sequence, validation criteria, and risks.
