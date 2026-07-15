begin;
create extension if not exists pgtap with schema extensions;
select plan(20);

select ok(
  (select bool_and(relrowsecurity)
   from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public' and c.relkind = 'r'),
  'RLS is enabled on every public table'
);

insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data)
values
  ('10000000-0000-0000-0000-000000000001', 'user-a@example.test', 'authenticated', 'authenticated', '{"provider":"google"}', '{}'),
  ('20000000-0000-0000-0000-000000000002', 'user-b@example.test', 'authenticated', 'authenticated', '{"provider":"google"}', '{}');

set local role authenticated;
select set_config('request.jwt.claim.sub', '10000000-0000-0000-0000-000000000001', true);
insert into public.wishlist_items (user_id, card_key, card_name)
values ('10000000-0000-0000-0000-000000000001', 'lightning-bolt', 'Lightning Bolt');
select is((select count(*) from public.wishlist_items), 1::bigint, 'owner can read own wishlist');
select lives_ok(
  $$
    insert into public.wishlist_items (
      user_id, card_key, card_name, desired_quantity, notes
    ) values (
      auth.uid(), 'lightning-bolt', 'Lightning Bolt', 2, 'upsert test'
    )
    on conflict (user_id, card_key) do update set
      user_id = excluded.user_id,
      card_key = excluded.card_key,
      card_name = excluded.card_name,
      desired_quantity = excluded.desired_quantity,
      notes = excluded.notes
  $$,
  'owner can upsert an existing wishlist item'
);
select is(
  (select price_alert_generation from public.configure_wishlist_price_alert(
    (select id from public.wishlist_items where card_key = 'lightning-bolt'), 1500, true
  )),
  1,
  'setting a target activates generation one'
);
select is(
  (select target_price_clp from public.wishlist_items where card_key = 'lightning-bolt'),
  1500,
  'target price is stored in CLP'
);
select ok(
  not has_function_privilege('authenticated', 'public.claim_price_tracker_card(uuid)', 'EXECUTE'),
  'authenticated clients cannot claim tracker work'
);
select ok(
  not has_column_privilege('authenticated', 'public.wishlist_items', 'last_price_clp', 'INSERT,UPDATE'),
  'authenticated clients cannot write internal tracker state'
);
select ok(
  has_table_privilege('service_role', 'public.price_tracker_runs', 'SELECT')
  and has_table_privilege('service_role', 'public.price_alert_deliveries', 'SELECT')
  and has_table_privilege('service_role', 'public.price_alert_deliveries', 'INSERT')
  and has_table_privilege('service_role', 'public.price_alert_deliveries', 'UPDATE')
  and has_table_privilege('service_role', 'public.price_alert_deliveries', 'DELETE'),
  'service role can maintain tracker queue and delivery outbox'
);
select throws_ok(
  $$update public.profiles set role = 'admin' where id = auth.uid()$$,
  '42501',
  null,
  'user cannot promote their own profile'
);

reset role;
set local role service_role;
select lives_ok(
  $$select public.start_or_resume_price_tracker_run()$$,
  'service role can start tracker run'
);
create temporary table claimed_tracker_card as
select * from public.claim_price_tracker_card((select id from public.price_tracker_runs where status = 'running'));
select is((select count(*) from claimed_tracker_card), 1::bigint, 'active wishlist card enters queue');
select is(
  public.record_price_tracker_result(
    (select id from claimed_tracker_card), 1500, 'Test Store', 'Lightning Bolt NM', 'https://example.test/bolt', 2
  ),
  1,
  'price equal to target queues an alert'
);
select public.record_price_tracker_result(
  (select id from claimed_tracker_card), 1400, 'Test Store', 'Lightning Bolt NM', 'https://example.test/bolt', 2
);
select is(
  (select count(*) from public.price_alert_deliveries),
  1::bigint,
  'recording the result twice cannot duplicate one generation'
);

reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000002', true);
select is((select count(*) from public.wishlist_items), 0::bigint, 'user B cannot read user A wishlist');
select is((select count(*) from public.price_alert_deliveries), 0::bigint, 'user B cannot read user A alerts');
select is(
  (select count(*) from public.search_runs where user_id = '10000000-0000-0000-0000-000000000001'),
  0::bigint,
  'user B cannot read user A searches'
);

reset role;
update public.profiles set status = 'suspended'
where id = '10000000-0000-0000-0000-000000000001';
set local role authenticated;
select set_config('request.jwt.claim.sub', '10000000-0000-0000-0000-000000000001', true);
select is((select count(*) from public.wishlist_items), 0::bigint, 'suspended user cannot read personal rows');
select throws_ok(
  $$insert into public.wishlist_items (user_id, card_key, card_name) values (auth.uid(), 'sol-ring', 'Sol Ring')$$,
  '42501',
  null,
  'suspended user cannot create personal rows'
);

reset role;
set local role anon;
select is((select count(*) from public.stores), 23::bigint, 'anonymous users can read active stores');
select throws_ok(
  $$select * from public.wishlist_items$$,
  '42501',
  null,
  'anonymous users cannot read wishlist'
);

select * from finish();
rollback;
