# Protein Source Helper

## Supabase schema

Run [`supabase/schema.sql`](./supabase/schema.sql) in the Supabase SQL Editor to
create the initial database schema. It defines retailers, retailer-specific
products, daily price and nutrition snapshots, and scraper run records.

Price and nutrition snapshots are unique per product and UTC calendar day.
Ingestion jobs should upsert snapshots using `(product_id, snapshot_date)`.
Nutrition values are stored per 100 g; `price_per_100g` is calculated for
products whose package size is recorded in grams.

The dashboard roles (`anon` and `authenticated`) can read active catalog data
and its history. Scraper writes should use a Supabase service-role key stored
only in a trusted environment such as GitHub Actions secrets; never expose it
in the public dashboard.