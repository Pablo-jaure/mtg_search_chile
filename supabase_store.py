from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


class SupabaseError(RuntimeError):
    """Raised when a Supabase API operation cannot be completed."""


def card_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name or "")
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    publishable_key: str
    secret_key: str

    @property
    def configured(self) -> bool:
        return bool(self.url and self.publishable_key and self.secret_key)


class SupabaseStore:
    def __init__(self, config: SupabaseConfig, timeout: float = 20.0):
        self.config = config
        self.base_url = config.url.rstrip("/")
        self.timeout = timeout

    def _headers(
        self,
        *,
        token: str | None = None,
        admin: bool = False,
        prefer: str | None = None,
    ) -> dict[str, str]:
        key = self.config.secret_key if admin else self.config.publishable_key
        headers = {
            "apikey": key,
            "Accept": "application/json",
            "User-Agent": "mtg-search-chile-backend/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        admin: bool = False,
        params: dict[str, Any] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(token=token, admin=admin, prefer=prefer),
                params=params,
                json=json,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise SupabaseError(f"No se pudo contactar Supabase: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise SupabaseError(
                f"Supabase respondió HTTP {response.status_code}: {detail}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def public_settings(self) -> dict[str, str]:
        return {
            "url": self.base_url,
            "publishable_key": self.config.publishable_key,
        }

    def authenticate(self, access_token: str) -> dict[str, Any] | None:
        if not access_token:
            return None
        try:
            auth_user = self._request(
                "GET", "/auth/v1/user", token=access_token
            )
            profiles = self._request(
                "GET",
                "/rest/v1/profiles",
                admin=True,
                params={"id": f"eq.{auth_user['id']}", "select": "*", "limit": 1},
            )
        except (KeyError, SupabaseError):
            return None
        if not profiles:
            return None
        profile = profiles[0]
        return {
            "id": auth_user["id"],
            "email": auth_user.get("email") or profile.get("email"),
            "profile": profile,
            "access_token": access_token,
        }

    def touch_last_seen(self, access_token: str, user_id: str) -> None:
        self._request(
            "PATCH",
            "/rest/v1/profiles",
            token=access_token,
            params={"id": f"eq.{user_id}"},
            json={"last_seen_at": datetime.now(timezone.utc).isoformat()},
            prefer="return=minimal",
        )

    def get_stores(self, access_token: str | None = None) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/rest/v1/stores",
            token=access_token,
            params={"select": "id,slug,name,platform,active", "order": "name.asc"},
        )

    def get_favorite_stores(self, access_token: str, user_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/rest/v1/favorite_stores",
            token=access_token,
            params={
                "user_id": f"eq.{user_id}",
                "select": "store_id,created_at,stores(id,slug,name,platform)",
                "order": "created_at.desc",
            },
        )

    def add_favorite_store(self, access_token: str, user_id: str, store_id: int) -> None:
        self._request(
            "POST",
            "/rest/v1/favorite_stores",
            token=access_token,
            json={"user_id": user_id, "store_id": store_id},
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def remove_favorite_store(self, access_token: str, user_id: str, store_id: int) -> None:
        self._request(
            "DELETE",
            "/rest/v1/favorite_stores",
            token=access_token,
            params={"user_id": f"eq.{user_id}", "store_id": f"eq.{store_id}"},
        )

    def get_wishlist(self, access_token: str, user_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/rest/v1/wishlist_items",
            token=access_token,
            params={"user_id": f"eq.{user_id}", "select": "*", "order": "created_at.desc"},
        )

    def save_wishlist_item(
        self,
        access_token: str,
        user_id: str,
        name: str,
        quantity: int,
        notes: str | None,
    ) -> dict[str, Any]:
        payload = {
            "user_id": user_id,
            "card_key": card_key(name),
            "card_name": name.strip(),
            "desired_quantity": max(1, min(int(quantity), 999)),
            "notes": (notes or "").strip()[:1000] or None,
        }
        rows = self._request(
            "POST",
            "/rest/v1/wishlist_items",
            token=access_token,
            params={"on_conflict": "user_id,card_key"},
            json=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0]

    def delete_wishlist_item(self, access_token: str, user_id: str, item_id: str) -> None:
        self._request(
            "DELETE",
            "/rest/v1/wishlist_items",
            token=access_token,
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
        )

    def update_wishlist_item(
        self, access_token: str, user_id: str, item_id: str, *, acquired: bool
    ) -> None:
        self._request(
            "PATCH",
            "/rest/v1/wishlist_items",
            token=access_token,
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
            json={"acquired": acquired},
            prefer="return=minimal",
        )

    def persist_search(
        self,
        access_token: str,
        user_id: str,
        query_text: str,
        cards: list[str],
        scryfall: dict[str, dict[str, Any]],
        results: list[dict[str, Any]],
        duration_ms: int,
    ) -> str:
        run_rows = self._request(
            "POST",
            "/rest/v1/search_runs",
            token=access_token,
            json={
                "user_id": user_id,
                "query_text": query_text[:20000],
                "status": "completed",
                "card_count": len(cards),
                "result_count": len(results),
                "duration_ms": max(0, duration_ms),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            prefer="return=representation",
        )
        run_id = run_rows[0]["id"]
        try:
            card_rows = self._request(
                "POST",
                "/rest/v1/search_cards",
                token=access_token,
                json=[
                    {
                        "search_run_id": run_id,
                        "card_key": card_key(name),
                        "searched_name": name,
                        "canonical_name": (scryfall.get(name) or {}).get("nombre_real"),
                        "image_url": (scryfall.get(name) or {}).get("imagen"),
                        "usd_price": (scryfall.get(name) or {}).get("usd"),
                    }
                    for name in cards
                ],
                prefer="return=representation",
            )
            card_ids = {row["card_key"]: row["id"] for row in card_rows}
            stores = self.get_stores(access_token)
            store_map = {row["name"]: row for row in stores}
            payload = []
            for result in results:
                store = store_map.get(result.get("Tienda"))
                search_card_id = card_ids.get(card_key(result.get("Carta Buscada", "")))
                if not store or not search_card_id:
                    continue
                snapshot = {}
                if result.get("Shopify Variant ID"):
                    snapshot["shopify_variant_id"] = result["Shopify Variant ID"]
                if result.get("WooCommerce Compra"):
                    snapshot["woocommerce"] = result["WooCommerce Compra"]
                payload.append(
                    {
                        "search_card_id": search_card_id,
                        "store_id": store["id"],
                        "product_name": result.get("Producto Encontrado") or "Producto",
                        "price_clp": int(result.get("Precio") or 0),
                        "product_url": result.get("Link") or "",
                        "in_stock": True,
                        "platform": store["platform"],
                        "purchase_snapshot": snapshot,
                    }
                )
            if payload:
                self._request(
                    "POST",
                    "/rest/v1/search_results",
                    token=access_token,
                    json=payload,
                    prefer="return=minimal",
                )
            return run_id
        except Exception:
            try:
                self._request(
                    "DELETE",
                    "/rest/v1/search_runs",
                    token=access_token,
                    params={"id": f"eq.{run_id}", "user_id": f"eq.{user_id}"},
                )
            finally:
                raise

    def get_search_history(self, access_token: str, user_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/rest/v1/search_runs",
            token=access_token,
            params={
                "user_id": f"eq.{user_id}",
                "select": "id,query_text,status,card_count,result_count,duration_ms,created_at,completed_at",
                "order": "created_at.desc",
                "limit": 100,
            },
        )

    def get_search_detail(self, access_token: str, user_id: str, run_id: str) -> dict[str, Any] | None:
        runs = self._request(
            "GET",
            "/rest/v1/search_runs",
            token=access_token,
            params={
                "id": f"eq.{run_id}",
                "user_id": f"eq.{user_id}",
                "select": "*",
                "limit": 1,
            },
        )
        if not runs:
            return None
        cards = self._request(
            "GET",
            "/rest/v1/search_cards",
            token=access_token,
            params={
                "search_run_id": f"eq.{run_id}",
                "select": "*,search_results(*,stores(name,slug,platform))",
                "order": "created_at.asc",
            },
        )
        return {"run": runs[0], "cards": cards}

    def delete_search(self, access_token: str, user_id: str, run_id: str | None = None) -> None:
        params = {"user_id": f"eq.{user_id}"}
        if run_id:
            params["id"] = f"eq.{run_id}"
        self._request("DELETE", "/rest/v1/search_runs", token=access_token, params=params)

    def record_cart_event(
        self,
        access_token: str,
        user_id: str,
        event: dict[str, Any],
    ) -> None:
        store_id = event.get("store_id")
        if not store_id and event.get("store_slug"):
            stores = self._request(
                "GET",
                "/rest/v1/stores",
                token=access_token,
                params={"slug": f"eq.{event['store_slug']}", "select": "id", "limit": 1},
            )
            store_id = stores[0]["id"] if stores else None
        self._request(
            "POST",
            "/rest/v1/cart_events",
            token=access_token,
            json={
                "user_id": user_id,
                "client_event_id": event.get("client_event_id"),
                "search_run_id": event.get("search_run_id"),
                "store_id": store_id,
                "platform": str(event.get("platform") or "external")[:50],
                "event_type": event.get("event_type") or "cart_opened",
                "estimated_total_clp": event.get("estimated_total_clp"),
                "card_count": max(1, min(int(event.get("card_count") or 1), 100)),
                "items": event.get("items") or [],
                "destination_url": str(event.get("destination_url") or "")[:4000],
            },
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def get_cart_history(self, access_token: str, user_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/rest/v1/cart_events",
            token=access_token,
            params={
                "user_id": f"eq.{user_id}",
                "select": "*,stores(name,slug)",
                "order": "created_at.desc",
                "limit": 200,
            },
        )

    def update_profile(self, access_token: str, user_id: str, payload: dict[str, Any]) -> None:
        allowed = {key: payload[key] for key in ("display_name", "deletion_requested_at") if key in payload}
        self._request(
            "PATCH",
            "/rest/v1/profiles",
            token=access_token,
            params={"id": f"eq.{user_id}"},
            json=allowed,
            prefer="return=minimal",
        )

    def account_counts(self, admin_user_id: str) -> dict[str, int]:
        rows = self._request(
            "GET",
            "/rest/v1/admin_user_summary",
            admin=True,
            params={"id": f"eq.{admin_user_id}", "select": "*", "limit": 1},
        )
        if not rows:
            return {"wishlist": 0, "favorites": 0, "searches": 0, "carts": 0}
        row = rows[0]
        return {
            "wishlist": row["wishlist_count"],
            "favorites": row["favorite_store_count"],
            "searches": row["search_count"],
            "carts": row["cart_event_count"],
        }

    def admin_users(self, search: str | None = None) -> list[dict[str, Any]]:
        params = {"select": "*", "order": "created_at.desc", "limit": 200}
        if search:
            safe = search.replace(",", "").replace("(", "").replace(")", "")
            params["or"] = f"(email.ilike.*{safe}*,display_name.ilike.*{safe}*)"
        return self._request("GET", "/rest/v1/admin_user_summary", admin=True, params=params)

    def admin_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/rest/v1/admin_audit_log",
            admin=True,
            params={"select": "*", "order": "created_at.desc", "limit": min(limit, 500)},
        )

    def admin_usage_metrics(self) -> dict[str, Any]:
        database = self._request(
            "GET", "/rest/v1/admin_database_metrics", admin=True, params={"select": "*", "limit": 1}
        )
        return {
            "database": database[0] if database else {},
            "stores": self._request(
                "GET", "/rest/v1/admin_store_usage", admin=True,
                params={"select": "*", "order": "cart_event_count.desc,result_count.desc", "limit": 20},
            ),
            "cards": self._request(
                "GET", "/rest/v1/admin_card_usage", admin=True,
                params={"select": "*", "order": "search_count.desc", "limit": 20},
            ),
            "daily": self._request(
                "GET", "/rest/v1/admin_daily_usage", admin=True,
                params={"select": "*", "order": "usage_date.desc", "limit": 30},
            ),
        }

    def admin_update_user(
        self,
        admin_id: str,
        target_id: str,
        *,
        role: str | None = None,
        status: str | None = None,
    ) -> None:
        targets = self._request(
            "GET",
            "/rest/v1/profiles",
            admin=True,
            params={"id": f"eq.{target_id}", "select": "id,role,status", "limit": 1},
        )
        if not targets:
            raise SupabaseError("Usuario no encontrado")
        target = targets[0]
        removing_active_admin = target["role"] == "admin" and target["status"] == "active" and (
            role == "user" or status == "suspended"
        )
        if removing_active_admin:
            active_admins = self._request(
                "GET",
                "/rest/v1/profiles",
                admin=True,
                params={"role": "eq.admin", "status": "eq.active", "select": "id"},
            )
            if len(active_admins) <= 1:
                raise SupabaseError("No se puede desactivar al último administrador activo")
        changes: dict[str, str] = {}
        if role in {"user", "admin"}:
            changes["role"] = role
        if status in {"active", "suspended"}:
            changes["status"] = status
        if not changes:
            raise SupabaseError("No hay cambios válidos")
        self._request(
            "PATCH",
            "/rest/v1/profiles",
            admin=True,
            params={"id": f"eq.{target_id}"},
            json=changes,
            prefer="return=minimal",
        )
        self._request(
            "POST",
            "/rest/v1/admin_audit_log",
            admin=True,
            json={
                "admin_user_id": admin_id,
                "target_user_id": target_id,
                "action": "user_updated",
                "metadata": changes,
            },
            prefer="return=minimal",
        )

    def admin_delete_user(self, admin_id: str, target_id: str) -> None:
        if admin_id == target_id:
            raise SupabaseError("No puedes eliminar tu propia cuenta desde el panel")
        target = self._request(
            "GET",
            "/rest/v1/profiles",
            admin=True,
            params={"id": f"eq.{target_id}", "select": "role,status", "limit": 1},
        )
        if target and target[0]["role"] == "admin" and target[0]["status"] == "active":
            active_admins = self._request(
                "GET",
                "/rest/v1/profiles",
                admin=True,
                params={"role": "eq.admin", "status": "eq.active", "select": "id"},
            )
            if len(active_admins) <= 1:
                raise SupabaseError("No se puede eliminar al último administrador activo")
        self._request(
            "POST",
            "/rest/v1/admin_audit_log",
            admin=True,
            json={
                "admin_user_id": admin_id,
                "target_user_id": target_id,
                "action": "user_deleted",
            },
            prefer="return=minimal",
        )
        self._request("DELETE", f"/auth/v1/admin/users/{target_id}", admin=True)
