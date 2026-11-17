INSERT INTO protein_source_helper.scrape_batch (scrape_batch_status)
VALUES ('running')
RETURNING scrape_batch_id;
