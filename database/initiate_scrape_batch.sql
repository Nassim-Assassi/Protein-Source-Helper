INSERT INTO public.scrape_batch (scrape_batch_status)
VALUES ('running')
RETURNING scrape_batch_id;
