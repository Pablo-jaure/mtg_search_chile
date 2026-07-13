# Plan de implementación: carrito WooCommerce

## Objetivo

Agregar en la vista **Por tienda** un botón que envíe al carrito real de una tienda WooCommerce la alternativa más barata con stock de cada carta buscada.

El comportamiento esperado debe ser equivalente al carrito Shopify actual:

- una unidad por carta;
- solo productos o variantes con stock verificado;
- elegir la oferta más barata cuando existan varias ediciones;
- mostrar cantidad de cartas y total estimado;
- terminar en el carrito real de la tienda.

## Diferencia con Shopify

Shopify permite construir un carrito mediante una URL estable:

```text
/cart/VARIANT_ID:1,VARIANT_ID:1
```

WooCommerce no incluye una URL estándar para agregar varios productos distintos al mismo tiempo. Para un producto simple normalmente acepta:

```text
/?add-to-cart=PRODUCT_ID&quantity=1
```

Las variantes requieren además `variation_id` y los atributos seleccionados. Algunos sitios modifican este flujo mediante temas, plugins, protección CSRF, AJAX o Cloudflare.

## Fase 1: obtener datos comprables

Extender `verificar_fichas_html()` para guardar en cada resultado:

```python
{
    "Plataforma": "woocommerce",
    "Product ID": "1234",
    "Variation ID": "5678",       # Opcional para productos simples
    "Atributos Variante": {
        "attribute_pa_condition": "near-mint"
    },
    "Cantidad": 1,
    "Stock Verificado": True,
}
```

Fuentes posibles, en orden de preferencia:

1. `form.cart` y su campo `add-to-cart`.
2. `button[name="add-to-cart"]` y su valor.
3. `data-product_id` en botones o enlaces.
4. `form.variations_form[data-product_variations]` para variantes.
5. JSON-LD como respaldo para precio y stock, pero no como fuente principal del ID comprable.

Para variantes se debe conservar exactamente la variante usada para calcular el precio y no volver a elegirla después.

## Fase 2: clasificar compatibilidad por tienda

Durante la cotización, asignar uno de estos estados:

- `compatible_simple`: acepta `?add-to-cart=ID`.
- `compatible_variacion`: acepta POST con variante y atributos.
- `ajax_personalizado`: requiere estudiar el endpoint del tema/plugin.
- `no_concluyente`: no fue posible obtener un ID comprable.
- `bloqueado`: Cloudflare, captcha u otra protección impide automatizarlo.

El diagnóstico debe mostrar el estado para que una tienda incompatible no genere un botón que falle silenciosamente.

## Fase 3: prueba de un solo producto

Antes del carrito múltiple, validar por tienda una carta conocida:

1. Construir la URL `/?add-to-cart=PRODUCT_ID&quantity=1`.
2. Abrirla en una sesión limpia del navegador.
3. Confirmar que redirige al carrito o muestra el aviso de producto agregado.
4. Confirmar nombre, variante, precio y cantidad.
5. Repetir con un producto variable cuando la tienda los utilice.

Guardar una configuración por tienda solamente cuando la prueba sea exitosa:

```python
WOOCOMMERCE_CART_CONFIG = {
    "Nombre Tienda": {
        "modo": "query_simple",
        "base_url": "https://tienda.cl",
        "cart_path": "/cart/",
    }
}
```

## Fase 4: agregar varios productos

### Opción recomendada: flujo secuencial en el navegador

Crear una página local intermedia `/carrito/woocommerce` que reciba las selecciones y guíe al navegador por las solicitudes de agregado una por una. Todas deben ejecutarse bajo el dominio de la tienda para conservar su cookie de sesión.

Flujo propuesto:

```text
Cotizador → agregar producto 1 → agregar producto 2 → ... → carrito de la tienda
```

La implementación debe:

- trabajar con una sola tienda por operación;
- procesar los productos secuencialmente;
- detenerse y mostrar qué producto falló;
- finalizar en la URL real del carrito;
- evitar solicitudes duplicadas al recargar.

No se recomienda crear el carrito con `httpx` desde Flask: la cookie generada en el servidor local no puede transferirse de forma segura al dominio de la tienda en el navegador.

### Alternativa por tienda: endpoint AJAX

Algunas tiendas exponen `/?wc-ajax=add_to_cart`. Puede usarse cuando se confirme que acepta solicitudes desde el navegador y no exige nonce adicional. Debe probarse individualmente debido a CORS, cookies `SameSite` y personalizaciones del tema.

## Fase 5: selección de ofertas

Reutilizar la regla implementada para Shopify:

1. Agrupar resultados por tienda.
2. Agrupar nuevamente por `Carta Buscada`.
3. Excluir productos sin `Stock Verificado` o sin ID comprable.
4. Elegir el menor precio por carta.
5. Calcular total y cantidad.

Si una tienda tiene stock para cinco cartas, pero solo tres poseen datos comprables, el botón debe indicar:

```text
Agregar 3 de 5 al carrito
```

También debe listar las dos cartas que deberán agregarse manualmente.

## Fase 6: interfaz

En **Por tienda**, mostrar el botón solo cuando exista al menos un producto compatible:

```text
🛒 Agregar 3 de 5 al carrito
Total estimado: $24.500
2 cartas requieren agregado manual
```

Antes de comenzar, mostrar una confirmación con:

- tienda de destino;
- cartas y variantes elegidas;
- precios observados;
- aviso de que el precio final lo determina la tienda.

## Fase 7: pruebas

### Pruebas unitarias

- extracción de `product_id` simple;
- extracción de `variation_id` y atributos;
- exclusión de variantes agotadas;
- elección de la alternativa más barata;
- construcción de parámetros sin duplicados;
- comportamiento cuando faltan IDs.

### Pruebas de integración por tienda

- una carta simple;
- una carta variable;
- dos o más cartas en la misma sesión;
- producto agotado entre cotización y agregado;
- cambio de precio entre cotización y carrito;
- bloqueo por Cloudflare o captcha;
- carrito previamente existente del usuario.

## Criterios de aceptación

La integración de una tienda WooCommerce estará lista cuando:

1. solo agregue productos con stock real;
2. respete la variante seleccionada;
3. agregue una unidad de cada carta elegida;
4. no duplique productos al navegar o recargar;
5. termine en el carrito real de la tienda;
6. informe claramente cartas omitidas o errores;
7. no dependa de credenciales ni almacene cookies del comprador en Flask.

## Orden recomendado de implementación

1. Extraer IDs de productos simples.
2. Validar una tienda WooCommerce sin protección.
3. Implementar el flujo secuencial para varios productos simples.
4. Añadir variantes y atributos.
5. Incorporar diagnóstico y cartas omitidas.
6. Habilitar tiendas una por una después de una prueba real.

