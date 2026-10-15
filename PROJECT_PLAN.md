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

The initial SQL is maintained in [`database/schema.sql`](./database/schema.sql).
The tables are:

- `retailer`: `retailer_id`, supermarket name, homepage URL, and active status.
- `brand`: `brand_id` and unique brand name.
- `category`: `category_id` and unique category name.
- `product`: `product_id`, `retailer_id`, optional `brand_id` and
  `category_id`, retailer-specific product identity, name, source URL, image
  URL, and active status.
- `snapshot`: `snapshot_id`, `product_id`, `scrape_run_id`,
  price, package quantity/unit, energy and protein values, optional additional
  nutrition values, nutrition basis, and source information. The related run's
  timestamps provide the collection window for its snapshots.
- `scrape_batch`: `scrape_batch_id`, which groups retailer-specific runs
  started together.
- `scrape_run`: `scrape_run_id`, `scrape_batch_id`, `retailer_id`, status,
  start/end times, and error details.

Primary key IDs use incrementing identity values: `snapshot_id` is `bigint`,
and all other IDs are `int`. Foreign key columns use the same type as the
referenced ID. Non-key columns are prefixed with their table name;
foreign keys use the referenced table's name, such as `product.retailer_id`
referencing `retailer.retailer_id`. Products can optionally reference a
normalized brand and category; deleting either lookup record leaves the
product in place and clears its corresponding ID. The external product ID is
not the database primary key; it is used with the retailer ID to identify a
retailer-specific product when available. Products with snapshots cannot be
deleted; mark them inactive to preserve their history.

The database supplies no defaults for application data. ETL writes must
explicitly provide required status flags and scrape-run timestamps/status.
Count snapshots by querying `snapshot` for that run rather than storing
duplicate counters. Identity primary keys remain database-managed.

Create one `scrape_batch` for each coordinated scrape launch, then create one
`scrape_run` per retailer in that batch. Each retailer run can succeed or fail
independently while retaining a shared ID for the overall launch.

### Data conventions and ingestion rules

1. Normalize nutrient values in the ETL before inserting snapshots. Store
   values only per 100 g or per 100 ml and record the basis accordingly.
   Convert per-serving values only when serving quantity and unit allow a
   reliable conversion; otherwise leave nutrition values unknown. Do not
   convert between grams and millilitres without a reliable density.
   Every snapshot must include energy and protein values on its stated basis;
   other nutrient values may be unknown.
2. Store package amount with an explicit unit (`g`, `ml`, or `each`); do not
   silently treat volume or count as weight.
3. Match products by retailer and external ID first; if no ID is available or
   no ID match exists, look up by retailer and canonical product URL before
   inserting. This lets ETL add a newly discovered external ID or update a
   changed URL without creating a duplicate.
4. Upsert each product snapshot by `(product_id, scrape_run_id)` so its price
   and nutrition values stay together. The product's retailer and scrape run's
   retailer must match.
5. Use the associated run's start and finish timestamps as the collection
   window for its snapshots. Keep the previous successful run visible while a
   later run is running, partial, or failed. Only mark a run successful in the
   same transaction that makes all its snapshots visible.
6. Keep source URLs so values can be investigated.
7. Treat missing non-required nutrition or package data as unknown, not zero.
   Do not write a snapshot if energy or protein is unavailable.
   If a product is absent from a scrape, do not write a snapshot for it. Mark
   it inactive only after it is absent from two consecutive successful runs
   for its retailer; failed runs do not count as missing observations. If it
   reappears, keep or reactivate it as active. Products omitted from the
   latest successful run are hidden from the dashboard immediately, even
   before the two-run threshold deactivates them.
8. Validate non-negative prices and nutrients and positive package quantities
   before writing.
9. Read current dashboard data from `current_data`, which returns products
   observed in each retailer's most recent successful run only, provided the
   run finished within the last 24 hours. It does not fall back to older
   snapshots for products omitted from that run; a retailer with no successful
   run in that window contributes no rows. Running and failed attempts do not
   replace the latest successful run; report their status separately when
   needed.

External product IDs are the preferred product identity. The schema has a
partial unique index on `(retailer_id, product_external_id)` when the ID is
present, and a separate fallback index on `(retailer_id, product_source_url)`
when it is absent. ETL should normalize empty IDs to `NULL`, canonicalize
product URLs, and use the matching partial-index conflict target.

Snapshots are restricted from deletion by either their product or scrape run;
deactivate products rather than deleting them so historical observations remain.

## 5. Metrics

- **Price per 100 g:** calculate from `snapshot_price` and
  `snapshot_package_quantity` for gram-based packages; do not persist the
  derived value.
- **Protein per 100 g:** protein value after converting source nutrient basis
  to 100 g.
- **Protein per pound:** calculate `snapshot_protein_g` against the price per
  100 g when both values use a per-100-g basis. Display the unit clearly
  (g protein per GBP).
- **Price versus category average:** product price metric compared with the
  average of comparable products in its category and package basis.
- **Best value:** rank products using protein per GBP, with transparent units
  and filters so unlike package types are not compared incorrectly.

Do not show computed metrics when inputs are absent, incomparable, or
ambiguous. The exact best-value ranking and treatment of promotions should be
validated before presenting it as a recommendation.

## 6. Delivery phases and acceptance criteria

### Phase 1 — Foundation

- Confirm product categories, retailer choice for the third supermarket, and
  PostgreSQL provider configuration.
- Apply and smoke-test the schema in a development PostgreSQL database.
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
supabase/
  schema.sql
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
Supabase and visible in a simple dashboard with search, price, protein per
100 g, and price per 100 g. Then add Sainsbury's and the selected third
retailer, improve comparisons, and automate daily runs. Confirm retailer
feasibility, data quality, and deployment requirements before expanding the
catalog.
