create index if not exists admin_audit_admin_user_idx
  on public.admin_audit_log (admin_user_id);
create index if not exists admin_audit_target_user_idx
  on public.admin_audit_log (target_user_id);
create index if not exists cart_events_search_run_idx
  on public.cart_events (search_run_id);
create index if not exists cart_events_store_idx
  on public.cart_events (store_id);
create index if not exists favorite_stores_store_idx
  on public.favorite_stores (store_id);

drop policy if exists admin_audit_admin_select on public.admin_audit_log;
create policy admin_audit_admin_select on public.admin_audit_log
for select to authenticated
using (private.is_admin((select auth.uid())));

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
for select to authenticated
using (id = (select auth.uid()) and private.is_active_user((select auth.uid())));

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
for update to authenticated
using (id = (select auth.uid()) and private.is_active_user((select auth.uid())))
with check (id = (select auth.uid()) and private.is_active_user((select auth.uid())));

drop policy if exists favorites_own_all on public.favorite_stores;
create policy favorites_own_all on public.favorite_stores
for all to authenticated
using (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())))
with check (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())));

drop policy if exists wishlist_own_all on public.wishlist_items;
create policy wishlist_own_all on public.wishlist_items
for all to authenticated
using (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())))
with check (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())));

drop policy if exists search_runs_own_all on public.search_runs;
create policy search_runs_own_all on public.search_runs
for all to authenticated
using (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())))
with check (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())));

drop policy if exists search_cards_own_all on public.search_cards;
create policy search_cards_own_all on public.search_cards
for all to authenticated
using (
  private.is_active_user((select auth.uid())) and exists (
    select 1 from public.search_runs r
    where r.id = search_run_id and r.user_id = (select auth.uid())
  )
)
with check (
  private.is_active_user((select auth.uid())) and exists (
    select 1 from public.search_runs r
    where r.id = search_run_id and r.user_id = (select auth.uid())
  )
);

drop policy if exists search_results_own_all on public.search_results;
create policy search_results_own_all on public.search_results
for all to authenticated
using (
  private.is_active_user((select auth.uid())) and exists (
    select 1 from public.search_cards c
    join public.search_runs r on r.id = c.search_run_id
    where c.id = search_card_id and r.user_id = (select auth.uid())
  )
)
with check (
  private.is_active_user((select auth.uid())) and exists (
    select 1 from public.search_cards c
    join public.search_runs r on r.id = c.search_run_id
    where c.id = search_card_id and r.user_id = (select auth.uid())
  )
);

drop policy if exists cart_events_own_all on public.cart_events;
create policy cart_events_own_all on public.cart_events
for all to authenticated
using (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())))
with check (user_id = (select auth.uid()) and private.is_active_user((select auth.uid())));
