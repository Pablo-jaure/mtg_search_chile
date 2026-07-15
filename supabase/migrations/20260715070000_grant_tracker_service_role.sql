-- The Edge Function uses the trusted service_role. RLS still protects these
-- tables from anon/authenticated clients, while the backend can inspect and
-- maintain the durable queue and email outbox.
grant select, insert, update, delete on table
  public.price_tracker_runs,
  public.price_tracker_run_cards,
  public.card_price_observations,
  public.price_alert_deliveries
to service_role;

grant usage, select on sequence public.card_price_observations_id_seq
to service_role;
