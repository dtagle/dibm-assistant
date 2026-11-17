# DIBM Assistant

Asistente que responde preguntas sobre los Documentos de Investigación del Banco de México
(https://www.banxico.org.mx/DIBM/): qué ha publicado un autor, cuáles son las publicaciones más recientes de un
año y de qué trata un documento. Trabaja sobre un snapshot del sitio (`data/publications.json`), con un solo
agente y cuatro herramientas de solo lectura. La API no guarda estado entre peticiones.

Cada petición es rastreable: lleva un `request_id`, deja eventos en un log JSON y suma a las métricas del
proceso. Opcionalmente, cada corrida del agente queda como traza en LangSmith.

Cada respuesta dice qué modelo usó, por qué y cuánto costó. El modelo real es Cloudflare Workers AI a través de
AI Gateway; el simulado (`fake`) responde sin red pero cobra con el precio del modelo cuyo nombre lleva.

## Cómo correrlo

Desde `product/`:

```bash
pip install -r requirements.txt
cp .env.example .env   # y llena los valores; .env nunca se sube al repositorio
uvicorn app.main:app --port 8000
```

- `GET /`: la página web. Tiene un campo de clave; cada respuesta muestra su `request_id` para pasarlo a
  soporte.
- `GET /health`: `{"status": "ok", "pid": ..., "publications": ...}`.
- `POST /ask` (pide `X-API-Key`): cuerpo `{"question": "...", "history": [...]}`. Responde `answer`, `steps`,
  `tools_used`, `input_tokens`, `output_tokens`, `request_id`, `model`, `route` (motivo del enrutador),
  `cached_calls` y `cost_usd`. Si el modelo real falla responde
  `502 {"detail": "model unavailable", "request_id": ...}`.
- `GET /metrics` (pide `X-API-Key`): `pid`, `requests`, `error_rate`, `latency_ms` (`p50`, `p95`), `tokens`
  (`input`, `output`), `cost_usd` acumulado y `slo` (`p95_ms_target`, `met`) de este proceso.
- `GET /docs`: la documentación de la API; no pide clave.

## Seguridad

- **Una clave por cliente.** `API_KEYS` tiene la forma `cliente:clave,cliente2:clave2`. `POST /ask` y
  `GET /metrics` exigen el encabezado `X-API-Key`; sin clave o con una inválida responden
  `401 {"detail": "invalid or missing API key"}`. La clave se compara en tiempo constante
  (`hmac.compare_digest`, `app/security.py`).
- **La clave nunca se escribe** en el log, en la traza ni en un error. Lo que sí se registra es el nombre del
  cliente: campo `client` en los eventos `agent_run` y `audit`, y en los metadatos de la traza.
- Si `API_KEYS` está mal formada, el producto no arranca; el error dice qué entrada falla (por posición) y su
  largo, nunca su valor.
- **Límite por cliente.** Más de `RATE_LIMIT_PER_MINUTE` peticiones en un minuto (ventana deslizante) responden
  `429 {"detail": "rate limit exceeded"}` con `Retry-After` en segundos. Usa el reloj inyectado. El estado vive
  en la memoria del proceso: con varias copias, el límite es por copia.
- **Compliance como código.** Con `ENVIRONMENT=production` el producto se niega a arrancar si `MODEL_PROVIDER`
  es `fake`, si `API_KEYS` está vacía o alguna clave tiene menos de 16 caracteres, o si las trazas están
  encendidas sin `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` (`app/compliance.py`). La tabla de reglas está en
  `doc/compliance-checklist.md`.
- **La página** guarda la clave en `sessionStorage` (se borra al cerrar la pestaña) y la manda en `X-API-Key`.
  Con `401` muestra «Clave inválida»; con `429`, «Demasiadas preguntas; espera N segundos».

## Costos

- **Modelo real** (`MODEL_PROVIDER=gateway`): `POST` a
  `https://gateway.ai.cloudflare.com/v1/{CF_ACCOUNT_ID}/{CF_GATEWAY_ID}/workers-ai/v1/chat/completions` con
  `Authorization: Bearer {CF_API_TOKEN}`. Los tokens salen de `usage`. Sin `CF_ACCOUNT_ID` o `CF_API_TOKEN` no
  arranca. Las pruebas inyectan un transporte `httpx` simulado: nunca usan la red.
- **Palanca 1, enrutamiento** (`app/router.py`): va a `MODEL_LARGE` si `ROUTING=false` (`routing_disabled`), si
  la pregunta pasa de `ROUTER_MAX_CHARS` (`long_question`) o si dice «compara», «resume», «explica», «por qué»,
  «analiza» o «todos» (`keyword`); si no, a `MODEL_SMALL` (`short_question`).
- **Palanca 2, ventana de historial**: al modelo solo van los últimos `HISTORY_WINDOW` mensajes del historial.
- **Palanca 3, tope de salida**: `MODEL_MAX_TOKENS` en cada llamada.
- **Palanca 4, caché de AI Gateway**: con `CACHE_TTL_SECONDS` mayor que 0 se manda `cf-aig-cache-ttl`; una
  respuesta con `cf-aig-cache-status: HIT` cuenta en `cached_calls` y no cuesta.
- **Precio**: `data/model_prices.json` (USD por millón de tokens, copia de `spec/model_prices.json`). Los dos
  modelos configurados deben tener precio o el producto no arranca.

Pruebas, con cobertura de 80 % o más:

```bash
pytest --cov=app --cov-fail-under=80
```

## Observabilidad

- **Id por petición.** Si el cliente manda `X-Request-ID`, se usa ese valor (ASCII visible, hasta 128
  caracteres); si no, se genera un UUID. Toda respuesta lo devuelve en el encabezado `X-Request-ID`.
- **Log JSON** en la salida estándar, una línea por evento, con `ts` (ISO 8601 en UTC), `service`, `event` y
  `request_id`:
  - `request`: `method`, `path`, `status` y `latency_ms`.
  - `agent_run`: `question_chars`, `history_messages`, `steps`, `tools`, `input_tokens`, `output_tokens` y
    `stopped`. Nunca el texto de la pregunta ni de la respuesta.
  - `audit`: `action: "tool_call"`, `tool` y `args`, uno por herramienta.
  - `error`: `error_type`, sin el mensaje. La respuesta es `500` con `{"detail": "internal error",
    "request_id": ...}`.
- **Para responder «¿qué pasó con la petición X?»**, filtra el log por `request_id`.
- La hora del log y las latencias salen de un reloj inyectado (`app/clock.py`), para que las pruebas sean
  deterministas.

## Variables de entorno

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MODEL_PROVIDER` | `fake` | `fake` (simulado, sin red) o `gateway` (Cloudflare) |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del bucle del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta |
| `PUBLICATIONS_PATH` | `data/publications.json` | El snapshot del DIBM |
| `SERVICE_NAME` | `dibm-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas en LangSmith |
| `LANGSMITH_API_KEY` | (sin valor) | Clave de LangSmith; sin ella no hay trazas ni conexión |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | No mandar a LangSmith el texto de preguntas ni respuestas |
| `CF_ACCOUNT_ID`, `CF_GATEWAY_ID`, `CF_API_TOKEN` | vacías, `default`, vacía | Cuenta, gateway y token de Cloudflare (el token es secreto) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan al modelo |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida |
| `MODEL_TEMPERATURE` | `0` | Con 0 las evaluaciones son repetibles (de 0 a 2) |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway en segundos (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo |
| `ENVIRONMENT` | `development` | `development` o `production`; con `production` se aplican las reglas de compliance |
| `API_KEYS` | vacía | Clientes y claves, `cliente:clave,cliente2:clave2` (secreto) |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto |

Un valor inválido (por ejemplo `AGENT_MAX_STEPS=0` o `SLO_P95_MS=rapido`) impide arrancar con un mensaje que
nombra la variable. Las claves de `API_KEYS`, la clave de LangSmith y el token de Cloudflare se leen del
entorno: nunca se escriben en el código, en el log ni en los mensajes de error. `.env.example` lista todas las variables con los secretos vacíos.

## Estructura

- `app/`: `main.py` (rutas y middleware), `agent.py`, `llm.py` (modelo simulado y real), `router.py`,
  `costs.py`, `prompts.py`, `tools.py`, `catalog.py`, `config.py`, `clock.py`, `observability.py` (log, id y
  métricas), `tracing.py` (LangSmith), `security.py` (clave y límite), `compliance.py` (reglas de
  producción) y `static/index.html`.
- `data/`: el snapshot y los precios por modelo.
- `tests/`: pruebas unitarias y escenarios Gherkin.
- `doc/`: arquitectura, ADR y `compliance-checklist.md`.
