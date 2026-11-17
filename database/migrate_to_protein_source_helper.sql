CREATE SCHEMA IF NOT EXISTS protein_source_helper;

ALTER TABLE IF EXISTS public.retailer SET SCHEMA protein_source_helper;
ALTER TABLE IF EXISTS public.retailer_category SET SCHEMA protein_source_helper;
ALTER TABLE IF EXISTS public.brand SET SCHEMA protein_source_helper;
ALTER TABLE IF EXISTS public.canonical_product SET SCHEMA protein_source_helper;
ALTER TABLE IF EXISTS public.retailer_listing SET SCHEMA protein_source_helper;
ALTER TABLE IF EXISTS public.scrape_batch SET SCHEMA protein_source_helper;
ALTER TABLE IF EXISTS public.scrape_run SET SCHEMA protein_source_helper;
ALTER TABLE IF EXISTS public.snapshot SET SCHEMA protein_source_helper;

ALTER MATERIALIZED VIEW IF EXISTS public.current_data_mat
    SET SCHEMA protein_source_helper;
ALTER VIEW IF EXISTS public.current_data SET SCHEMA protein_source_helper;
