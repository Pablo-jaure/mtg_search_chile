import pytest

from supabase_store import SupabaseConfig, SupabaseError, SupabaseStore, card_key


def test_card_key_normalizes_accents():
    assert card_key("Dragón's Rage Channeler") == "dragon-s-rage-channeler"


def test_secret_key_is_not_sent_as_bearer():
    store = SupabaseStore(SupabaseConfig("https://x", "sb_publishable_public", "sb_secret_private"))
    headers = store._headers(admin=True)
    assert headers["apikey"] == "sb_secret_private"
    assert "Authorization" not in headers


def test_access_token_is_the_only_bearer():
    store = SupabaseStore(SupabaseConfig("https://x", "public", "secret"))
    assert store._headers(token="jwt")["Authorization"] == "Bearer jwt"


def test_last_admin_cannot_be_demoted(monkeypatch):
    store = SupabaseStore(SupabaseConfig("https://x", "public", "secret"))
    replies = iter([[{"id": "a", "role": "admin", "status": "active"}], [{"id": "a"}]])
    monkeypatch.setattr(store, "_request", lambda *args, **kwargs: next(replies))
    with pytest.raises(SupabaseError, match="administrador"):
        store.admin_update_user("a", "a", role="user", status="active")


def test_configure_price_alert_uses_authenticated_rpc(monkeypatch):
    store = SupabaseStore(SupabaseConfig("https://x", "public", "secret"))
    captured = {}
    def fake_request(method, path, **kwargs):
        captured.update(method=method, path=path, **kwargs)
        return {"id": "item-1"}
    monkeypatch.setattr(store, "_request", fake_request)
    store.configure_wishlist_price_alert("jwt", "item-1", 1500, True)
    assert captured["path"] == "/rest/v1/rpc/configure_wishlist_price_alert"
    assert captured["token"] == "jwt"
    assert captured["json"]["p_target_price_clp"] == 1500


def test_wishlist_storage_keeps_legacy_quantity_at_one(monkeypatch):
    store = SupabaseStore(SupabaseConfig("https://x", "public", "secret"))
    captured = {}

    def fake_request(method, path, **kwargs):
        captured.update(method=method, path=path, **kwargs)
        return [{"id": "item-1"}]

    monkeypatch.setattr(store, "_request", fake_request)
    store.save_wishlist_item("jwt", "user-1", " Lightning Bolt ", "  Foil  ")

    assert captured["json"]["desired_quantity"] == 1
    assert captured["json"]["card_name"] == "Lightning Bolt"
    assert captured["json"]["notes"] == "Foil"
