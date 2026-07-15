-- Users create wishlist cards, while tracker state is only changed through the
-- authenticated configuration RPC or service-only processing RPCs.
revoke insert on public.wishlist_items from authenticated;
grant insert (user_id, card_key, card_name, desired_quantity, notes, acquired)
  on public.wishlist_items to authenticated;

