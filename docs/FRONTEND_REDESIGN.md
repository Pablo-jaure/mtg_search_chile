# Frontend de MTG Search Chile

## Sistema visual

La interfaz mantiene Bootstrap como base y agrega una capa propia en
`static/css/app.css`. Los tokens principales viven en `:root`: colores,
superficies, bordes, radios, sombras y ancho máximo del contenido.

La identidad usa azul marino para navegación y jerarquía, rojo cálido para la
acción principal, azul para información y verde exclusivamente para precio,
stock y estados positivos.

Los componentes Jinja reutilizables están en `templates/_components.html`:

- encabezados de página;
- estados vacíos;
- tarjetas de métricas;
- badges de estado.

Los mensajes flash están aislados en `templates/_flash_messages.html`.

## Responsive

- Desde `768px`, las ofertas se presentan como tabla.
- Bajo `768px`, cada oferta se transforma en una tarjeta apilada.
- En mobile se muestran inicialmente ocho ofertas por carta y el usuario puede
  expandir el resto.
- La grilla de tiendas y las métricas se adaptan sin scroll horizontal.
- El mínimo soportado es `320px`.

## Limitaciones de datos

- La wishlist no guarda actualmente `image_url` ni identificador de Scryfall.
  Por eso el rediseño no inventa una imagen para cada elemento. Una mejora
  futura puede persistir esos campos al agregar una carta.
- El total estimado por tienda solo se muestra cuando existe integración de
  carrito Shopify o WooCommerce. Para el resto se muestran mínimo, promedio,
  cobertura y cantidad de productos, sin presentar un total ficticio.
- Los resultados del scraper representan productos encontrados con stock; el
  backend no entrega una etiqueta de stock adicional por oferta.

