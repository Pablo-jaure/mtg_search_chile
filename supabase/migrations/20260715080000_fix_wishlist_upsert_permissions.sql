-- PostgREST's merge-duplicates upsert updates every column present in the
-- payload. These are all user-managed wishlist fields; tracker state remains
-- unavailable to authenticated clients. RLS still enforces user_id = auth.uid().
grant update (user_id, card_key, card_name, desired_quantity, notes, acquired)
on public.wishlist_items to authenticated;
