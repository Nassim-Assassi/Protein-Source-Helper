# Protein Source Helper - Project Plan

## 1. Objective

Expand the existing Morrisons-backed static dashboard into a broader, reliable,
public protein-value comparison service. Future work should improve retailer
coverage, discovery, comparison tools, automation, and operational monitoring
without weakening the existing database and scraping contracts.

## 2. Remaining product scope

### Dashboard experience

- Add product-name and brand search.
- Add retailer, category, maximum-price, and protein-threshold filters.
- Add sorting and comparison views that account for package size and compatible units.
- Display a clearly defined protein-per-pound value alongside existing price and
  protein metrics.
- Show latest successful refresh, newest attempt status, stale data, and
  per-retailer coverage.
- Handle loading, empty, stale, and query-error states clearly.
- Improve mobile and keyboard interactions for all interactive controls.

### Retailer expansion

- Add Sainsbury's extraction and test representative product categories.
- Evaluate Tesco and Asda, then implement the selected third retailer.
- Investigate Aldi, Lidl, Waitrose, and Ocado after core data quality is stable.
- Review each retailer's terms, access conditions, technical approach, and
  change risk before implementation.

### Catalog expansion

- Broaden coverage only where extraction and nutrition quality are dependable.
- Prioritize chicken, fish, beef mince, Greek yogurt, cottage cheese, eggs,
  tofu or tempeh, beans and pulses, protein shakes and bars, and high-protein
  ready meals or snacks.
- Keep coverage intentionally curated rather than attempting a complete catalog
  of every grocery product.

### Historical views

- Add price history once enough daily snapshots have accumulated.
- Add retailer-level movement and trend views.
- Preserve an explicit refresh timestamp and collection window for every trend.

## 3. Remaining architecture work

- Add new retailer adapters behind the existing module contract.
- Extend shared request pacing, retries, structured logging, and error reporting
  as retailer-specific failures require.
- Improve identity matching and nutrition parsing while preserving the loader's
  validated payload contract.
- Add scheduled batch execution and predictable retry behavior to GitHub Actions.
- Add operator monitoring for stale data, run failures, snapshot counts, and
  retailer-specific extraction degradation.
- Keep the static dashboard read-only and credential-free by expanding only the
  generated JSON export contract.

## 4. Future data and contract work

- Improve fallback identity matching when retailer IDs are unstable or missing.
- Expand canonical-brand and category matching across retailers.
- Improve serving-size and nutrition-basis conversion coverage.
- Add a formal data-quality report for skipped, malformed, duplicate, stale,
  and out-of-stock observations.
- Define migration and compatibility rules before changing snapshot or metric
  schemas.

## 5. Future metrics and ranking work

- **Protein per pound:** display with explicit currency and units using
  comparable package or 100 g values.
- **Price versus category average:** calculate only within compatible package
  units and an agreed retailer/category scope.
- **Promotion-adjusted value:** decide whether promotional prices are eligible
  before adding a recommendation or rank.
- Add regression tests for missing, zero, incomparable, and ambiguous values.
- Document the ranking formula and mark rankings as informational where the
  underlying comparisons are not methodologically complete.

## 6. Delivery phases

### Phase 1 - Dashboard discovery

- Add product search and name/brand filtering.
- Add retailer, category, price, and protein filters.
- Add sortable and comparable product results.
- Add a product detail or comparison view.
- Improve loading, empty, stale, error, and no-results states.

**Done when:** visitors can find and compare eligible products through a clear,
keyboard-accessible interface.

### Phase 2 - Retailer expansion

- Add Sainsbury's extraction using the shared payload contract.
- Evaluate Tesco and Asda and implement the selected third retailer.
- Test representative categories and nutrition formats for every enabled retailer.
- Review extraction limitations and isolate retailer failures.

**Done when:** every enabled adapter produces the shared payload and a failed
retailer run does not prevent successful retailers from loading.

### Phase 3 - Automation and publishing

- Change the batch workflow from manual dispatch to a scheduled daily run.
- Keep manual dispatch for on-demand refreshes.
- Refresh the materialized view after committed scrape results.
- Generate and publish dashboard data after a successful or partial batch.
- Make retries and reruns avoid duplicate snapshots.

**Done when:** a scheduled end-to-end run produces fresh dashboard data and
failed or partial runs are diagnosable without exposing secrets.

### Phase 4 - Static dashboard hardening

- Validate database-derived source URLs and allow only safe link schemes.
- Add normal, empty, malformed, and unexpected-data rendering tests.
- Cover keyboard activation and tab selection for ranking controls.
- Deterministically close exporter database connections in repeated runs.

**Done when:** malformed data cannot create unsafe links or break rendering,
and rendering behavior is covered by automated tests.

### Phase 5 - Monitoring and trends

- Add success/failure rates and stale-data monitoring.
- Alert or log retailer-specific extraction degradation.
- Improve identity matching and nutrition parsing from observed failures.
- Add price history and retailer movement views after enough snapshots exist.
- Investigate additional supermarkets only after core quality and monitoring are reliable.

**Done when:** operators can identify stale or degraded data and resolve it
without compromising other retailers or the rest of the service.

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Retailer markup, APIs, or embedded product data changes | Keep adapters isolated, test representative URLs, and log parse failures. |
| Access restrictions or anti-bot responses | Review retailer terms, use modest rates, avoid account-only pages, and stop rather than bypass access controls. |
| Inconsistent nutrition bases and units | Normalize explicitly, retain source/basis metadata, and never calculate from ambiguous inputs. |
| Product IDs change or are missing | Prefer external IDs and test a deterministic retailer-specific URL fallback. |
| Duplicate products or repeated snapshots | Retain database uniqueness constraints and deterministic upserts. |
| Price promotions make comparisons misleading | Capture observed price and timestamp and define promotion treatment before ranking. |
| One retailer breaks the whole batch | Isolate adapter execution and record independent per-retailer outcomes. |
| Database credentials leak | Keep credentials in trusted runtime secrets and apply least-privilege permissions. |
| Static dashboard output becomes unsafe | Validate generated links and rendered values and test malformed database-derived data. |

## 8. Responsible collection and security

- Review each retailer's terms and applicable access rules before collection.
- Collect only public product information; do not access personal or
  account-specific data.
- Use reasonable delays and avoid unnecessary page requests.
- Keep secrets out of source control, logs, and client-side dashboard code.
- Give the ingestion worker write access only as required, and give the
  dashboard read-only access to the catalog data it needs.

## 9. Future sequencing

1. Add dashboard search, filtering, sorting, and missing-data states.
2. Schedule and harden end-to-end batch publishing.
3. Add Sainsbury's extraction and representative product tests.
4. Evaluate and add the selected third retailer.
5. Complete dashboard and exporter accessibility and security hardening.
6. Add monitoring, price history, and additional retailers as data quality
   and operator confidence improve.
