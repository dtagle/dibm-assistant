# 0004 Interfaz de modelo con modelo simulado y gateway

## Contexto

Las pruebas, el contrato y la evaluación de costos deben correr sin red ni cuota, y el modelo real debe poder
cambiarse sin tocar el agente.

## Decisión

El agente solo conoce `complete(messages)`, que devuelve texto, tokens de entrada y salida y si fue cacheado.
`FakeLLM` aplica las reglas deterministas de la spec 01 y recibe la lista de apellidos inyectada. `GatewayLLM` llama
a Cloudflare AI Gateway con httpx. `MODEL_PROVIDER` elige la implementación; `create_app()` la recibe inyectada. El
nombre del modelo simulado (`MODEL_SMALL` o `MODEL_LARGE`) solo afecta el precio.

## Consecuencias

- Pruebas y evaluación repetibles y gratis; las palancas de costo se miden con el simulado.
- El simulado no mide calidad real del lenguaje; la evaluación con gateway queda a cargo de una persona.
- Un fallo del gateway se traduce a `502 model unavailable` en un solo lugar.
