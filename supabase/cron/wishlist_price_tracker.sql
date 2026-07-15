-- Run after the Edge Function and these Vault secrets exist:
-- price_tracker_function_url, price_tracker_cron_secret
create extension if not exists pg_cron;
create extension if not exists pg_net;
create extension if not exists supabase_vault;

do $$
declare existing_job bigint;
begin
  select jobid into existing_job from cron.job where jobname = 'wishlist-price-tracker-6h';
  if existing_job is not null then perform cron.unschedule(existing_job); end if;
  perform cron.schedule(
    'wishlist-price-tracker-6h',
    '5 */6 * * *',
    $job$
      select net.http_post(
        url := (select decrypted_secret from vault.decrypted_secrets where name = 'price_tracker_function_url'),
        headers := jsonb_build_object(
          'Content-Type', 'application/json',
          'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'price_tracker_cron_secret')
        ),
        body := '{"scheduled":true}'::jsonb,
        timeout_milliseconds := 10000
      );
    $job$
  );
end $$;

