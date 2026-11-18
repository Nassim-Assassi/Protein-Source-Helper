-- Current retailer data and dashboard metrics

DROP VIEW IF EXISTS protein_source_helper.current_data;
DROP MATERIALIZED VIEW IF EXISTS protein_source_helper.current_data_mat;

CREATE MATERIALIZED VIEW protein_source_helper.current_data_mat AS
WITH latest_successful_run AS (
    SELECT DISTINCT ON (retailer_id)
        scrape_run_id,
        retailer_id,
        scrape_run_started_at,
        scrape_run_finished_at
    FROM protein_source_helper.scrape_run
    WHERE
        scrape_run_status = 'succeeded'
        AND scrape_run_finished_at
        >= statement_timestamp() - interval '26 hours'
    ORDER BY retailer_id ASC, scrape_run_finished_at DESC, scrape_run_id DESC
),

current_metrics AS (
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
                WHEN s.snapshot_nutrition_basis = 'per_item'
                    THEN s.snapshot_energy_kcal * s.snapshot_package_quantity
                WHEN s.snapshot_nutrition_basis IN ('per_100g', 'per_100ml')
                    THEN
                        s.snapshot_energy_kcal * s.snapshot_package_quantity
                        / 100.0
            END,
            2
        ) AS total_energy_kcal,
        round(
            CASE
                WHEN s.snapshot_nutrition_basis = 'per_item'
                    THEN s.snapshot_protein_g * s.snapshot_package_quantity
                WHEN s.snapshot_nutrition_basis IN ('per_100g', 'per_100ml')
                    THEN
                        s.snapshot_protein_g * s.snapshot_package_quantity
                        / 100.0
            END,
            2
        ) AS total_protein_g,
        round(
            CASE
                WHEN s.snapshot_energy_kcal > 0
                    THEN
                        CASE
                            WHEN
                                s.snapshot_nutrition_basis = 'per_item'
                                AND s.snapshot_package_unit = 'each'
                                THEN
                                    (
                                        s.snapshot_price
                                        / (
                                            s.snapshot_energy_kcal
                                            * s.snapshot_package_quantity
                                        )
                                    ) * 100
                            WHEN
                                s.snapshot_nutrition_basis = 'per_100g'
                                AND s.snapshot_package_unit = 'g'
                                THEN
                                    (
                                        s.snapshot_price
                                        / (
                                            (s.snapshot_energy_kcal / 100.0)
                                            * s.snapshot_package_quantity
                                        )
                                    ) * 100
                            WHEN
                                s.snapshot_nutrition_basis = 'per_100ml'
                                AND s.snapshot_package_unit = 'ml'
                                THEN
                                    (
                                        s.snapshot_price
                                        / (
                                            (s.snapshot_energy_kcal / 100.0)
                                            * s.snapshot_package_quantity
                                        )
                                    ) * 100
                        END
            END, 2
        ) AS cost_per_100_kcal,
        round(
            CASE
                WHEN s.snapshot_energy_kcal > 0
                    THEN
                        (s.snapshot_protein_g / s.snapshot_energy_kcal) * 100
            END, 2
        ) AS protein_g_per_100_kcal,
        round(
            CASE
                WHEN s.snapshot_protein_g > 0
                    THEN
                        (100.0 * s.snapshot_price) / CASE
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
            END, 4
        ) AS cost_per_100g_protein
    FROM latest_successful_run AS latest
    INNER JOIN protein_source_helper.snapshot AS s
        ON
            latest.scrape_run_id = s.scrape_run_id
            AND latest.retailer_id = s.retailer_id
    INNER JOIN protein_source_helper.retailer_listing AS rl
        ON
            s.retailer_listing_id = rl.retailer_listing_id
            AND s.retailer_id = rl.retailer_id
    INNER JOIN protein_source_helper.retailer AS r
        ON rl.retailer_id = r.retailer_id
    LEFT JOIN protein_source_helper.canonical_product AS cp
        ON rl.canonical_product_id = cp.canonical_product_id
    LEFT JOIN protein_source_helper.brand AS b
        ON cp.brand_id = b.brand_id
    LEFT JOIN protein_source_helper.retailer_category AS rc
        ON
            rl.retailer_category_id = rc.retailer_category_id
            AND rl.retailer_id = rc.retailer_id
    WHERE
        rl.retailer_listing_active = true
        AND r.retailer_active = true
        AND s.snapshot_out_of_stock = false
),

score_benchmarks AS (
    SELECT
        0.14::numeric AS good_cost_per_100_kcal,
        1.40::numeric AS poor_cost_per_100_kcal,
        4.5833::numeric AS good_cost_per_100g_protein,
        79.5374::numeric AS poor_cost_per_100g_protein
),

normalized_data AS (
    SELECT
        current_metrics.*,
        CASE
            WHEN current_metrics.cost_per_100_kcal IS NOT null
                THEN
                    round(
                        least(
                            100.0,
                            greatest(
                                0.0,
                                100.0
                                * (
                                    benchmarks.poor_cost_per_100_kcal
                                    - current_metrics.cost_per_100_kcal
                                )
                                / (
                                    benchmarks.poor_cost_per_100_kcal
                                    - benchmarks.good_cost_per_100_kcal
                                )
                            )
                        ),
                        2
                    )
        END AS cost_per_100_kcal_normalized_score,
        CASE
            WHEN current_metrics.cost_per_100g_protein IS NOT null
                THEN
                    round(
                        least(
                            100.0,
                            greatest(
                                0.0,
                                100.0
                                * (
                                    benchmarks.poor_cost_per_100g_protein
                                    - current_metrics.cost_per_100g_protein
                                )
                                / (
                                    benchmarks.poor_cost_per_100g_protein
                                    - benchmarks.good_cost_per_100g_protein
                                )
                            )
                        ),
                        2
                    )
        END AS cost_per_100g_protein_normalized_score
    FROM current_metrics
    CROSS JOIN score_benchmarks AS benchmarks
),

value_scores AS (
    SELECT
        scores.*,
        CASE
            WHEN
                scores.cost_per_100_kcal_normalized_score
                IS NOT null
                AND
                scores.cost_per_100g_protein_normalized_score
                IS NOT null
                THEN
                    round(
                        (
                            scores.cost_per_100_kcal_normalized_score
                            + scores.cost_per_100g_protein_normalized_score
                        ) / 2.0,
                        2
                    )
        END AS value_score,
        CASE
            WHEN scores.protein_g_per_100_kcal IS NOT null
                THEN
                    round(
                        least(
                            100.0,
                            greatest(0.0, 4.0 * scores.protein_g_per_100_kcal)
                        ),
                        2
                    )
        END AS protein_score
    FROM normalized_data AS scores
),

overall_scores AS (
    SELECT
        scores.*,
        CASE
            WHEN
                scores.value_score IS NOT null
                AND scores.protein_score IS NOT null
                THEN round((scores.value_score + scores.protein_score) / 2.0, 2)
        END AS balanced_overall_score,
        CASE
            WHEN
                scores.value_score IS NOT null
                AND scores.protein_score IS NOT null
                THEN
                    round(
                        0.75 * scores.value_score
                        + 0.25 * scores.protein_score,
                        2
                    )
        END AS value_focused_overall_score,
        CASE
            WHEN
                scores.value_score IS NOT null
                AND scores.protein_score IS NOT null
                THEN
                    round(
                        0.25 * scores.value_score
                        + 0.75 * scores.protein_score,
                        2
                    )
        END AS protein_focused_overall_score
    FROM value_scores AS scores
)

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
    total_energy_kcal,
    total_protein_g,
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
    cost_per_100_kcal,
    cost_per_100_kcal_normalized_score,
    protein_g_per_100_kcal,
    cost_per_100g_protein,
    cost_per_100g_protein_normalized_score,
    value_score,
    protein_score,
    balanced_overall_score,
    value_focused_overall_score,
    protein_focused_overall_score
FROM overall_scores;

CREATE UNIQUE INDEX current_data_mat_listing_id_idx
ON protein_source_helper.current_data_mat (retailer_listing_id);

CREATE INDEX current_data_mat_protein_per_100_kcal_idx
ON protein_source_helper.current_data_mat (
    protein_g_per_100_kcal DESC NULLS LAST
);

CREATE INDEX current_data_mat_cost_per_100g_protein_idx
ON protein_source_helper.current_data_mat (
    cost_per_100g_protein ASC NULLS LAST
);

CREATE INDEX current_data_mat_canonical_id_idx
ON protein_source_helper.current_data_mat (canonical_product_id);

CREATE VIEW protein_source_helper.current_data AS
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
    total_energy_kcal,
    total_protein_g,
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
    cost_per_100_kcal,
    cost_per_100_kcal_normalized_score,
    protein_g_per_100_kcal,
    cost_per_100g_protein,
    cost_per_100g_protein_normalized_score,
    value_score,
    protein_score,
    balanced_overall_score,
    value_focused_overall_score,
    protein_focused_overall_score
FROM protein_source_helper.current_data_mat
WHERE scrape_run_finished_at >= statement_timestamp() - interval '26 hours';
