-- Refreshes the materialized view "current_data_mat" in the public schema.

REFRESH MATERIALIZED VIEW CONCURRENTLY public.current_data_mat;