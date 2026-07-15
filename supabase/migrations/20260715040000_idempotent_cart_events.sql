alter table public.cart_events
  add column if not exists client_event_id uuid;

create unique index if not exists cart_events_user_client_event_idx
  on public.cart_events (user_id, client_event_id)
  where client_event_id is not null;
