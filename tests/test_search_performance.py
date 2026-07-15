import asyncio

import app


class ShopifyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "variants": [
                {"available": True, "price": 199000, "id": 123, "title": "Normal"}
            ]
        }


class ConcurrentClient:
    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def get(self, *_args, **_kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return ShopifyResponse()


def test_shopify_detail_requests_run_concurrently_with_shared_limit():
    client = ConcurrentClient()
    resultados = [
        {
            "Carta Buscada": "Lightning Bolt",
            "Tienda": "Tienda",
            "Producto Encontrado": f"Lightning Bolt {indice}",
            "Precio": 2500,
            "Link": f"https://example.com/products/bolt-{indice}",
        }
        for indice in range(6)
    ]

    actualizados = asyncio.run(
        app.actualizar_precios_shopify(client, resultados, asyncio.Semaphore(3))
    )

    assert len(actualizados) == 6
    assert client.max_active == 3
    assert all(resultado["Precio"] == 1990 for resultado in actualizados)
    assert all(resultado["Stock Verificado"] is True for resultado in actualizados)
