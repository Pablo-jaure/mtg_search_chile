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
