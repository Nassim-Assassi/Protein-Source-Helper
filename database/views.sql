-- Current retailer data and dashboard metrics

DROP VIEW IF EXISTS public.current_data;
DROP MATERIALIZED VIEW IF EXISTS public.current_data_mat;

CREATE MATERIALIZED VIEW public.current_data_mat AS
WITH latest_successful_run AS (
    SELECT DISTINCT ON (retailer_id)
        scrape_run_id,
        retailer_id,
        scrape_run_started_at,
        scrape_run_finished_at
    FROM public.scrape_run
    WHERE
        scrape_run_status = 'succeeded'
        AND scrape_run_finished_at
        >= statement_timestamp() - interval '26 hours'
    ORDER BY retailer_id ASC, scrape_run_finished_at DESC, scrape_run_id DESC
)

SELECT
    cp.canonical_product_id,
    cp.canonical_product_name,
    cp.barcode_gtin AS canonical_barcode_gtin,
    rl.retailer_listing_id,
    rl.retailer_listing_name,
    rl.retailer_listing_external_id,
    rl.retailer_listing_source_url,
    rl.retailer_listing_image_url,
    rl.retailer_listing_active,
    r.retailer_id,
    r.retailer_name,
    r.retailer_url,
    b.brand_id,
    b.brand_name,
    rc.retailer_category_id,
    rc.retailer_category_name,
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
    latest.scrape_run_id,
    latest.scrape_run_started_at,
    latest.scrape_run_finished_at,
    round(
        CASE
            WHEN
                s.snapshot_package_quantity > 0
                THEN (s.snapshot_price / s.snapshot_package_quantity) * 100
        END, 2
    ) AS price_per_100_units,
    round(
        CASE
            WHEN s.snapshot_price > 0 AND s.snapshot_package_quantity > 0
                THEN
                    (
                        CASE
                            WHEN
                                s.snapshot_nutrition_basis = 'per_item'
                                AND s.snapshot_package_unit = 'each'
                                THEN
                                    s.snapshot_protein_g
                                    * s.snapshot_package_quantity
                            WHEN
                                s.snapshot_nutrition_basis = 'per_100g'
                                AND s.snapshot_package_unit = 'g'
                                THEN
                                    (s.snapshot_protein_g / 100.0)
                                    * s.snapshot_package_quantity
                            WHEN
                                s.snapshot_nutrition_basis = 'per_100ml'
                                AND s.snapshot_package_unit = 'ml'
                                THEN
                                    (s.snapshot_protein_g / 100.0)
                                    * s.snapshot_package_quantity
                        END
                    ) / s.snapshot_price
        END, 2
    ) AS total_protein_grams_per_currency_unit
FROM latest_successful_run AS latest
INNER JOIN public.snapshot AS s
    ON
        latest.scrape_run_id = s.scrape_run_id
        AND latest.retailer_id = s.retailer_id
INNER JOIN public.retailer_listing AS rl
    ON
        s.retailer_listing_id = rl.retailer_listing_id
        AND s.retailer_id = rl.retailer_id
INNER JOIN public.retailer AS r
    ON rl.retailer_id = r.retailer_id
LEFT JOIN public.canonical_product AS cp
    ON rl.canonical_product_id = cp.canonical_product_id
LEFT JOIN public.brand AS b
    ON cp.brand_id = b.brand_id
LEFT JOIN public.retailer_category AS rc
    ON
        rl.retailer_category_id = rc.retailer_category_id
        AND rl.retailer_id = rc.retailer_id
WHERE
    rl.retailer_listing_active = true
    AND r.retailer_active = true
    AND s.snapshot_out_of_stock = false;

CREATE UNIQUE INDEX current_data_mat_listing_id_idx
ON public.current_data_mat (retailer_listing_id);

CREATE INDEX current_data_mat_protein_per_cost_idx
ON public.current_data_mat (
    total_protein_grams_per_currency_unit DESC NULLS LAST
);

CREATE INDEX current_data_mat_canonical_id_idx
ON public.current_data_mat (canonical_product_id);

CREATE VIEW public.current_data AS
SELECT
    canonical_product_id,
    canonical_product_name,
    canonical_barcode_gtin,
    retailer_listing_id,
    retailer_listing_name,
    retailer_listing_external_id,
    retailer_listing_source_url,
    retailer_listing_image_url,
    retailer_listing_active,
    retailer_id,
    retailer_name,
    retailer_url,
    brand_id,
    brand_name,
    retailer_category_id,
    retailer_category_name,
    snapshot_id,
    snapshot_price,
    snapshot_package_quantity,
    snapshot_package_unit,
    snapshot_energy_kcal,
    snapshot_protein_g,
    snapshot_carbohydrates_g,
    snapshot_sugars_g,
    snapshot_fat_g,
    snapshot_saturates_g,
    snapshot_fibre_g,
    snapshot_salt_g,
    snapshot_nutrition_basis,
    snapshot_nutrition_source,
    snapshot_out_of_stock,
    scrape_run_id,
    scrape_run_started_at,
    scrape_run_finished_at,
    price_per_100_units,
    total_protein_grams_per_currency_unit
FROM public.current_data_mat
WHERE scrape_run_finished_at >= statement_timestamp() - interval '26 hours';