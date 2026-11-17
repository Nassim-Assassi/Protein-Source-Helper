-- Refreshes the materialized view "current_data_mat" in the application schema.

REFRESH MATERIALIZED VIEW CONCURRENTLY protein_source_helper.current_data_mat;
