begin;
create extension if not exists pgtap with schema extensions;
select plan(9);

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
select throws_ok(
  $$update public.profiles set role = 'admin' where id = auth.uid()$$,
  '42501',
  null,
  'user cannot promote their own profile'
);

reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000002', true);
select is((select count(*) from public.wishlist_items), 0::bigint, 'user B cannot read user A wishlist');
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
