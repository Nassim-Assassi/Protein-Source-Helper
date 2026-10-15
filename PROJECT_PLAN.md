# Protein Source Helper — Project Plan

## 1. Objective

Build a public-facing dashboard that helps UK shoppers compare protein-focused
grocery products by price, nutrition, and value. The first release should be
small enough to validate the product while establishing a reusable foundation
for additional categories and supermarkets.

## 2. MVP scope

### Users and outcomes

Shoppers should be able to:

- Search products by product name or brand.
- Filter by retailer, category, maximum price, and protein threshold.
- Compare price, package size, protein per 100 g, and price per 100 g.
- Find lower-cost and higher-protein-per-pound options.
- See when data was last refreshed.

Price history and retailer movement are follow-on dashboard views once enough
daily snapshots have accumulated.

### Retailers

- Initial retailer: Morrisons.
- Next retailer: Sainsbury's.
- Third retailer: choose Tesco or Asda after a small technical feasibility
  check.
- Later candidates: Aldi, Lidl, Waitrose, and Ocado.

Retailer coverage is a target, not a claim that working scrapers already exist.
Each retailer's terms, access conditions, and technical approach must be
reviewed before implementation.

### Initial product categories

Start with a curated selection of high-protein products: chicken, salmon and
other fish, beef mince, Greek yogurt, cottage cheese, eggs, tofu or tempeh,
beans and pulses, protein shakes and bars, and selected high-protein ready
meals and snacks. Avoid attempting to catalog all supermarket groceries.

## 3. Architecture

```text
Retailer product pages
        |
        v
Python retailer adapters --> shared parsing and normalization
        |                             |
        +-----------------------------+
                      |
                      v
              PostgreSQL
          products + daily snapshots
                      |
                      v
             Streamlit dashboard

GitHub Actions schedules scraper runs and captures run outcomes.
```

### Component responsibilities

- **Retailer adapters:** Fetch and extract retailer-specific product details;
  isolate retailer selectors, embedded data parsing, and source quirks.
- **Shared scraper utilities:** Provide common request/session handling,
  respectful pacing, retry policy, logging, and error reporting.
- **Normalization and validation:** Convert product and nutrient values into
  the common model, standardize units, and reject or flag invalid records.
- **PostgreSQL:** Persist retailer/product identity and dated price/nutrition
  observations. The schema avoids provider-specific APIs and roles; configure
  application roles and permissions separately for the chosen host.
- **Streamlit:** Query read-only catalog data and provide searchable,
  filterable comparisons.
- **GitHub Actions:** Run ingestion daily, retain actionable logs, and expose
  failed or partial runs for diagnosis.

## 4. Data model

The current SQL is maintained in [`database/schema.sql`](./database/schema.sql).
It defines:

- `retailer`: retailer name, URL, and active status.
- `retailer_category`: category names scoped to a retailer.
- `brand`: normalized brand names.
- `canonical_product`: canonical product name, optional GTIN, and optional
  brand.
- `retailer_listing`: retailer-specific name, external ID, source and image
  URLs, active status, canonical product, and optional retailer category.
- `scrape_batch`: one coordinated scrape launch, with status and timestamps.
- `scrape_run`: one retailer's run within a batch, with status, timestamps,
  and error details. A batch may be partial while an individual run is
  succeeded or failed.
- `snapshot`: one listing's price, package quantity/unit, required energy and
  protein values, optional nutrients, nutrition basis/source, and stock state
  as observed in a scrape run.

Primary key IDs use incrementing identity values: `snapshot_id` is `bigint`,
and all other IDs are `int`. Foreign keys use the referenced ID's type.
Retailer listings are unique by `(retailer_id, retailer_listing_external_id)`
when the external ID is present; when it is absent, they are unique by
`(retailer_id, retailer_listing_source_url)`. Snapshots are unique by
`(retailer_listing_id, scrape_run_id)`. Composite foreign keys ensure a
snapshot's listing and scrape run belong to the same retailer. Identity
primary keys remain database-managed; status values and required data must be
provided by ingestion, while timestamps and active/stock flags have defaults
where defined.

Create one `scrape_batch` for each coordinated scrape launch, then one
`scrape_run` per retailer in that batch. Each retailer run can succeed or fail
independently while retaining a shared ID for the overall launch. Snapshot
counts can be derived by querying snapshots for the run.

### Data conventions and ingestion rules

1. Normalize nutrient values in the ETL before inserting snapshots. Store
  values per 100 g, per 100 ml, or per item and record the basis accordingly.
   Convert per-serving values only when serving quantity and unit allow a
   reliable conversion; otherwise leave nutrition values unknown. Do not
   convert between grams and millilitres without a reliable density.
   Every snapshot must include energy and protein values on its stated basis;
   other nutrient values may be unknown.
2. Store package amount with an explicit unit (`g`, `ml`, or `each`); do not
   silently treat volume or count as weight.
3. Match listings by retailer and external ID when present; if no external ID
  is present, use retailer and source URL. Normalize empty IDs to `NULL` and
  canonicalize URLs before matching. The schema's URL uniqueness rule applies
  only when the external ID is `NULL`.
4. Upsert each snapshot by `(retailer_listing_id, scrape_run_id)` so its price
  and nutrition values stay together. The listing's retailer and scrape run's
  retailer must match.
5. Use the associated run's start and finish timestamps as the collection
  window for its snapshots. Keep the previous successful run visible while a
  later run is running or failed. Only mark a run successful once its
  snapshots are complete and visible.
6. Keep source URLs so values can be investigated.
7. Treat missing non-required nutrition data as unknown, not zero. Package
  quantity and unit are required for every snapshot. Do not write a snapshot
  if energy or protein is unavailable.
  If a product is absent from a scrape, do not write a snapshot for it. Mark
   it inactive only after it is absent from two consecutive successful runs
   for its retailer; failed runs do not count as missing observations. If it
   reappears, keep or reactivate it as active. Products omitted from the
   latest successful run are hidden from the dashboard immediately, even
   before the two-run threshold deactivates them.
8. Validate non-negative prices and nutrients and positive package quantities
   before writing.
9. Read dashboard data from `current_data`, not directly from
  `current_data_mat`. The materialized view contains in-stock snapshots from
  each retailer's most recent successful run finished within the last 26
  hours at the time it was refreshed. It does not fall back to an older
  snapshot for a listing omitted from that run. The regular `current_data`
  view applies the same 26-hour freshness check at query time, so expired rows
  are hidden between refreshes. A retailer with no qualifying successful run
  contributes no rows. Running and failed attempts do not replace the latest
  successful run; report their status separately when needed.

The schema restricts deletion of listings referenced by snapshots and of runs
referenced by snapshots. Deactivate listings rather than deleting them so
historical observations remain.

External IDs are the preferred listing identity. The schema enforces
retailer-scoped uniqueness on `retailer_listing_external_id` when present and
on `retailer_listing_source_url` when the external ID is `NULL`. ETL should
normalize empty external IDs to `NULL` and canonicalize source URLs before
matching.

## 5. Metrics

The current `current_data_mat` view calculates `price_per_100_units` from
package price and quantity, and `total_protein_grams_per_currency_unit` from
the nutrition basis, package quantity, and price. The first metric can
represent grams, millilitres, or eaches; it is not a like-for-like price per
100 g metric. Treat comparisons across different package units as a known
limitation until the metric is split or normalized. The regular `current_data`
view exposes these columns with the same freshness filter.

Planned dashboard metrics include:

- **Price per 100 g:** calculate only for gram-based packages with compatible
  units; do not persist the derived value.
- **Protein per 100 g:** display only when the stored nutrition basis supports
  it or can be reliably normalized.
- **Protein per pound:** display with explicit currency and units, using
  comparable price and protein values.
- **Price versus category average:** compare only products with compatible
  package units and category scope.
- **Best value:** rank by protein per pound only when inputs are present and
  comparable.

Do not show computed metrics when inputs are absent, incomparable, or
ambiguous. The exact best-value ranking and treatment of promotions should be
validated before presenting it as a recommendation.

## 6. Delivery phases and acceptance criteria

### Phase 1 — Foundation

- Confirm product categories, retailer choice for the third supermarket, and
  PostgreSQL provider configuration.
- Apply and smoke-test the schema in a development PostgreSQL database.
- Remember that `database/initial_database_setup.sh` resets the database's
  application tables and dependent objects before applying the schema.
- Define environment variable names and secret handling without committing
  credentials.
- Agree the normalized product and snapshot payloads.

**Done when:** the schema applies cleanly, sample records can be written and
queried, and the data contract is documented.

### Phase 2 — Morrisons ingestion

- Build shared scraper primitives and a Morrisons adapter.
- Start from the curated links in `morrisons_mvp_links.txt` and category data
  in `morrisons_product_categories.csv`.
- Extract product identity, name, brand, category, price, package size, and
  nutrition where available.
- Add validation, rate limiting, structured logs, and scrape-run records.

**Done when:** a small representative set of product pages can be processed
repeatedly; valid records upsert without duplicates; unavailable or malformed
fields are reported rather than silently fabricated.

### Phase 3 — Add retailers

- Add a Sainsbury's adapter using the shared normalized output.
- Evaluate Tesco versus Asda for the third retailer and implement the selected
  adapter.
- Record retailer-specific extraction limitations and test representative
  products for each supported category.

**Done when:** all enabled adapters produce the same validated payload shape,
and failure in one retailer does not prevent other retailers from completing.

### Phase 4 — Dashboard MVP

- Create an overview with product counts, retailers, and latest run status/time.
- Add search and retailer/category/price/protein filters.
- Add sortable product results with price, package size, price per 100 g, and
  protein per 100 g.
- Add product comparison and a protein-per-pound best-value view.
- Handle loading, empty, stale, and query-error states clearly.

**Done when:** a visitor can find and compare products using current stored
data without access to scraper credentials.

### Phase 5 — Daily automation

- Add a GitHub Actions workflow with a daily schedule and manual dispatch.
- Supply PostgreSQL connection credentials using repository/environment
  secrets.
- Persist scrape-run status and counts; ensure failure and partial completion
  are visible in logs.
- Refresh `current_data_mat` after scrape results are committed; the dashboard
  reads the freshness-filtered `current_data` view.
- Make jobs safe to retry and avoid duplicate daily snapshots.

**Done when:** a scheduled run completes end-to-end, its output appears in the
dashboard, and failed runs are diagnosable without exposing secrets.

### Phase 6 — Monitoring and improvement

- Track success/failure rates, snapshot counts per run, and stale data.
- Review extraction changes and data anomalies on a regular cadence.
- Improve identity matching, nutrition parsing, and category coverage.
- Add price trends and more retailers only after core data quality is reliable.

**Done when:** operators can detect stale or degraded data and resolve a
retailer-specific breakage without compromising the rest of the service.

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Retailer markup, APIs, or embedded product data changes | Keep adapters isolated, test representative URLs, and log parse failures. |
| Access restrictions or anti-bot responses | Review retailer terms, use modest rates, avoid account-only pages, and stop rather than bypass access controls. |
| Inconsistent nutrition bases and units | Normalize explicitly, retain source/basis metadata where available, and do not calculate from ambiguous inputs. |
| Product IDs change or are missing | Prefer retailer external IDs; define and test fallback identity rules per retailer. |
| Duplicate products or repeated snapshots | Use database uniqueness constraints and deterministic upserts. |
| Price promotions make comparisons misleading | Capture observed price and timestamp; clarify promotion treatment before ranking. |
| One retailer breaks the whole daily job | Isolate adapter execution and record per-retailer outcomes. |
| Database credentials leak | Keep credentials only in trusted runtime secrets and give each application only the permissions it needs. |

## 8. Responsible collection and security

- Review each retailer's terms and applicable access rules before collection.
- Collect only public product information; do not access personal or
  account-specific data.
- Use reasonable delays and avoid unnecessary page requests.
- Keep secrets out of source control, logs, and client-side dashboard code.
- Give the ingestion worker write access only as required, and give the
  dashboard read-only access to the catalog data it needs.

## 9. Suggested repository layout

```text
database/
  schema.sql
  initial_database_setup.sh
  refresh_materialised_view.sh
  refresh_materialised_view.sql
scraper/
  core.py
  normalize.py
  run_daily.py
  retailers/
    morrisons.py
    sainsburys.py
    tesco_or_asda.py
dashboard/
  app.py
.github/
  workflows/
    daily-scrape.yml
```

This is a target structure for implementation, not a description of files
already present. Keep the layout simple as the project grows and avoid adding
components that the MVP does not yet need.

## 10. Initial milestone and sequencing

The first usable milestone is a small set of Morrisons products ingested into
PostgreSQL and visible in a simple dashboard with search, price, protein per
100 g, and price per 100 g. Then add Sainsbury's and the selected third
retailer, improve comparisons, and automate daily runs. Confirm retailer
feasibility, data quality, and deployment requirements before expanding the
catalog.
