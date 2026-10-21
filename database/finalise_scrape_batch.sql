UPDATE public.scrape_batch
SET
    scrape_batch_status = :'batch_status',
    scrape_batch_finished_at = clock_timestamp(),
    scrape_batch_error_message = NULLIF(:'error_message', '')
WHERE
    scrape_batch_id = :'batch_id'::integer
    AND scrape_batch_status = 'running';
