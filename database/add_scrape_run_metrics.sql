ALTER TABLE public.scrape_run
    ADD COLUMN IF NOT EXISTS scrape_run_discovered_count int
        CHECK (scrape_run_discovered_count >= 0),
    ADD COLUMN IF NOT EXISTS scrape_run_extracted_count int
        CHECK (scrape_run_extracted_count >= 0),
    ADD COLUMN IF NOT EXISTS scrape_run_extraction_failed_count int
        CHECK (scrape_run_extraction_failed_count >= 0),
    ADD COLUMN IF NOT EXISTS scrape_run_transformed_count int
        CHECK (scrape_run_transformed_count >= 0),
    ADD COLUMN IF NOT EXISTS scrape_run_transformation_skipped_count int
        CHECK (scrape_run_transformation_skipped_count >= 0),
    ADD COLUMN IF NOT EXISTS scrape_run_loaded_count int
        CHECK (scrape_run_loaded_count >= 0),
    ADD COLUMN IF NOT EXISTS scrape_run_extraction_duration_seconds
        double precision CHECK (
            scrape_run_extraction_duration_seconds >= 0
        ),
    ADD COLUMN IF NOT EXISTS scrape_run_transformation_duration_seconds
        double precision CHECK (
            scrape_run_transformation_duration_seconds >= 0
        ),
    ADD COLUMN IF NOT EXISTS scrape_run_load_duration_seconds
        double precision CHECK (scrape_run_load_duration_seconds >= 0);