--Materialized view to hold the latest data.

DROP MATERIALIZED VIEW IF EXISTS public.current_data_mat CASCADE;

CREATE MATERIALIZED VIEW public.current_data_mat AS
WITH latest_successful_run AS (
    SELECT DISTINCT ON (retailer_id)
        scrape_run_id,
        retailer_id,
        scrape_run_started_at,
        scrape_run_finished_at
    FROM public.scrape_run
    WHERE scrape_run_status = 'succeeded'
      AND scrape_run_finished_at >= statement_timestamp() - interval '26 hours'
    ORDER BY retailer_id, scrape_run_finished_at DESC, scrape_run_id DESC
)
SELECT
    -- Canonical Product Details (Nullable)
    cp.canonical_product_id,
    cp.canonical_product_name,
    cp.barcode_gtin AS canonical_barcode_gtin,

    -- Retailer Listing Details
    rl.retailer_listing_id,
    rl.retailer_listing_name,
    rl.retailer_listing_external_id,
    rl.retailer_listing_source_url,
    rl.retailer_listing_image_url,
    rl.retailer_listing_active,

    -- Retailer Details
    r.retailer_id,
    r.retailer_name,
    r.retailer_url,
    
    -- Brand & Category (Nullable)
    b.brand_id,
    b.brand_name,
    c.category_id,
    c.category_name,
    
    -- Latest Successful Snapshot Data
    s.snapshot_id,
    s.snapshot_price,
    s.snapshot_package_quantity,
    s.snapshot_package_unit,
    s.snapshot_energy_kcal,
    s.snapshot_protein_g,
    s.snapshot_carbohydrates_g,
    s.snapshot_sugars_g,
    s.snapshot_fat_g,
    s.snapshot_saturates_g,
    s.snapshot_fibre_g,
    s.snapshot_salt_g,
    s.snapshot_nutrition_basis,
    s.snapshot_nutrition_source,
    s.snapshot_out_of_stock,

    -- Computed Dashboard Metrics
    ROUND(
        CASE 
            WHEN s.snapshot_package_quantity > 0 THEN (s.snapshot_price / s.snapshot_package_quantity) * 100
            ELSE NULL 
        END, 2
    ) AS price_per_100_units,

    ROUND(
        CASE 
            WHEN s.snapshot_price > 0 AND s.snapshot_package_quantity > 0 THEN
                (
                    CASE
                        WHEN s.snapshot_nutrition_basis = 'per_item'
                            AND s.snapshot_package_unit = 'each'
                            THEN s.snapshot_protein_g * s.snapshot_package_quantity
                        WHEN s.snapshot_nutrition_basis = 'per_100g'
                            AND s.snapshot_package_unit = 'g'
                            THEN (s.snapshot_protein_g / 100.0) * s.snapshot_package_quantity
                        WHEN s.snapshot_nutrition_basis = 'per_100ml'
                            AND s.snapshot_package_unit = 'ml'
                            THEN (s.snapshot_protein_g / 100.0) * s.snapshot_package_quantity
                        ELSE NULL
                    END
                ) / s.snapshot_price
            ELSE NULL 
        END, 2
    ) AS total_protein_grams_per_currency_unit,

    -- Associated Run Details
    latest.scrape_run_id,
    latest.scrape_run_started_at,
    latest.scrape_run_finished_at
FROM latest_successful_run latest
JOIN public.snapshot s
    ON s.scrape_run_id = latest.scrape_run_id
   AND s.retailer_id = latest.retailer_id
JOIN public.retailer_listing rl
    ON rl.retailer_listing_id = s.retailer_listing_id
   AND rl.retailer_id = s.retailer_id
JOIN public.retailer r 
    ON r.retailer_id = rl.retailer_id
LEFT JOIN public.brand b 
    ON b.brand_id = rl.brand_id
LEFT JOIN public.category c 
    ON c.category_id = rl.category_id
LEFT JOIN public.canonical_product cp
    ON cp.canonical_product_id = rl.canonical_product_id
WHERE rl.retailer_listing_active = true 
  AND r.retailer_active = true
  AND s.snapshot_out_of_stock = false;

-- Required unique index for CONCURRENT refresh
CREATE UNIQUE INDEX current_data_mat_listing_id_idx 
    ON public.current_data_mat (retailer_listing_id);

-- Purpose-built indexes for dashboard filtering and ranking
CREATE INDEX current_data_mat_protein_per_cost_idx 
    ON public.current_data_mat (total_protein_grams_per_currency_unit DESC NULLS LAST);

CREATE INDEX current_data_mat_canonical_id_idx 
    ON public.current_data_mat (canonical_product_id);