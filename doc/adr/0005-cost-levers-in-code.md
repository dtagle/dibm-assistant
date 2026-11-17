# 0005 Palancas de costo con reglas en código y medidas

## Contexto

Cada respuesta tiene costo por tokens. Bajarlo no debe empeorar la calidad.

## Decisión

Cuatro palancas configurables: enrutamiento por una regla en código (largo de la pregunta y palabras como
«compara» o «resume») entre `MODEL_SMALL` y `MODEL_LARGE`; ventana de historial `HISTORY_WINDOW`; tope de salida
`MODEL_MAX_TOKENS`; caché de AI Gateway con `CACHE_TTL_SECONDS`. El costo se calcula con `data/model_prices.json` y
se reporta por respuesta (`cost_usd`, `model`, `route`, `cached_calls`) y acumulado en `/metrics`.

## Consecuencias

- El enrutador no cuesta tokens y es explicable (`route` dice el motivo).
- Una palanca solo se deja encendida si la evaluación muestra que la calidad no baja y el costo sí.
- Los precios cambian: el archivo se revisa antes de usarlo y un modelo sin precio es error de arranque.
