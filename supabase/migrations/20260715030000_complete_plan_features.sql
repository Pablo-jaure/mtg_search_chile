alter table public.wishlist_items
  add column if not exists acquired boolean not null default false;

drop view if exists public.admin_user_summary;
create view public.admin_user_summary
with (security_invoker = true)
as
select
  p.id,
  p.email,
  p.display_name,
  p.avatar_url,
  p.provider,
  p.role,
  p.status,
  p.last_seen_at,
  p.deletion_requested_at,
  p.created_at,
  count(distinct w.id) as wishlist_count,
  count(distinct f.store_id) as favorite_store_count,
  count(distinct sr.id) as search_count,
  count(distinct ce.id) as cart_event_count,
  count(distinct result.id) as result_count
from public.profiles p
left join public.wishlist_items w on w.user_id = p.id
left join public.favorite_stores f on f.user_id = p.id
left join public.search_runs sr on sr.user_id = p.id
left join public.search_cards sc on sc.search_run_id = sr.id
left join public.search_results result on result.search_card_id = sc.id
left join public.cart_events ce on ce.user_id = p.id
group by p.id;

revoke all on public.admin_user_summary from public, anon, authenticated;
grant select on public.admin_user_summary to service_role;

create or replace view public.admin_store_usage
with (security_invoker = true)
as
select
  s.id,
  s.slug,
  s.name,
  count(distinct r.id) as result_count,
  count(distinct c.id) as cart_event_count,
  coalesce(sum(c.estimated_total_clp), 0) as estimated_cart_total_clp
from public.stores s
left join public.search_results r on r.store_id = s.id
left join public.cart_events c on c.store_id = s.id
group by s.id;

create or replace view public.admin_card_usage
with (security_invoker = true)
as
select
  coalesce(nullif(c.canonical_name, ''), c.searched_name) as card_name,
  count(*) as search_count,
  count(r.id) as result_count
from public.search_cards c
left join public.search_results r on r.search_card_id = c.id
group by coalesce(nullif(c.canonical_name, ''), c.searched_name);

create or replace view public.admin_daily_usage
with (security_invoker = true)
as
select
  date(created_at) as usage_date,
  count(*) as search_count,
  coalesce(avg(result_count), 0)::numeric(12, 2) as average_results,
  count(*) filter (where status in ('failed', 'partial')) as persistence_error_count
from public.search_runs
where created_at >= now() - interval '90 days'
group by date(created_at);

create or replace view public.admin_database_metrics
with (security_invoker = true)
as
select
  coalesce(sum(pg_total_relation_size(c.oid)), 0) as public_tables_bytes,
  (select count(*) from public.profiles where status = 'active') as active_accounts,
  (select count(*) from public.profiles where status = 'active' and last_seen_at >= now() - interval '30 days') as active_users_30d
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('r', 'm');

revoke all on public.admin_store_usage from public, anon, authenticated;
revoke all on public.admin_card_usage from public, anon, authenticated;
revoke all on public.admin_daily_usage from public, anon, authenticated;
revoke all on public.admin_database_metrics from public, anon, authenticated;
grant select on public.admin_store_usage to service_role;
grant select on public.admin_card_usage to service_role;
grant select on public.admin_daily_usage to service_role;
grant select on public.admin_database_metrics to service_role;
