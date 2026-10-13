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
            Supabase Postgres
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
- **Supabase:** Persist retailer/product identity and dated price/nutrition
  observations.
- **Streamlit:** Query read-only catalog data and provide searchable,
  filterable comparisons.
- **GitHub Actions:** Run ingestion daily, retain actionable logs, and expose
  failed or partial runs for diagnosis.

## 4. Data model

The initial SQL is maintained in [`supabase/schema.sql`](./supabase/schema.sql).
The tables are:

- `retailers`: supermarket name, domain, and active status.
- `products`: retailer-specific product identity, name, brand, category,
  source URL, image URL, and active status.
- `price_snapshots`: dated price and package quantity/unit, with generated
  `price_per_100g` for gram-based packages.
- `nutrition_snapshots`: dated energy, protein, carbohydrates, sugars, fat,
  saturates, fibre, salt, serving size, and source.
- `scrape_runs`: retailer, status, start/end times, counts, and error details.

Primary keys use incrementing `bigint` identity values, and foreign keys use
matching `bigint` columns. The external product ID is not the database primary
key; it is used with the retailer ID to identify a retailer-specific product
when available.

### Data conventions and ingestion rules

1. Store nutrient values normalized to per 100 g where possible, and retain
   serving size when supplied.
2. Store package amount with an explicit unit (`g`, `ml`, or `each`); do not
   silently treat volume or count as weight.
3. Upsert products by `(retailer_id, external_product_id)` when an external ID
   exists. Define a retailer-specific fallback identity when it does not.
4. Upsert daily price and nutrition snapshots by
   `(product_id, snapshot_date)` to avoid duplicate same-day observations.
5. Use UTC calendar dates consistently for daily snapshots.
6. Keep source URL and collection time so values can be investigated.
7. Treat missing nutrition or package data as unknown, not zero.
8. Validate non-negative prices and nutrients and positive package quantities
   before writing.

## 5. Metrics

- **Price per 100 g:** `price / package_quantity_g * 100`.
- **Protein per 100 g:** protein value after converting source nutrient basis
  to 100 g.
- **Protein per pound:** `protein_g_per_100g / price_per_100g` when both values
  use a per-100-g basis. Display the unit clearly (g protein per GBP).
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
  Supabase project configuration.
- Apply and smoke-test the schema in a development Supabase project.
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

- Create an overview with product counts, retailers, and last successful sync.
- Add search and retailer/category/price/protein filters.
- Add sortable product results with price, package size, price per 100 g, and
  protein per 100 g.
- Add product comparison and a protein-per-pound best-value view.
- Handle loading, empty, stale, and query-error states clearly.

**Done when:** a visitor can find and compare products using current stored
data without access to scraper credentials.

### Phase 5 — Daily automation

- Add a GitHub Actions workflow with a daily schedule and manual dispatch.
- Supply Supabase credentials using repository/environment secrets.
- Persist scrape-run status and counts; ensure failure and partial completion
  are visible in logs.
- Make jobs safe to retry and avoid duplicate daily snapshots.

**Done when:** a scheduled run completes end-to-end, its output appears in the
dashboard, and failed runs are diagnosable without exposing secrets.

### Phase 6 — Monitoring and improvement

- Track success/partial/failure rates, products seen/updated, and stale data.
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
| Supabase service credentials leak | Keep service-role keys only in trusted runtime secrets; dashboard uses read-only access. |

## 8. Responsible collection and security

- Review each retailer's terms and applicable access rules before collection.
- Collect only public product information; do not access personal or
  account-specific data.
- Use reasonable delays and avoid unnecessary page requests.
- Keep secrets out of source control, logs, and client-side dashboard code.
- Use the service-role key only for trusted ingestion workers.
- Restrict public dashboard access to the catalog data it needs.

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
