# 0006 Seguridad y compliance como código al arrancar

## Contexto

El servicio se publica en Render con un modelo de pago. Hay que controlar quién lo usa, cuánto y que nunca se
filtren claves ni textos de personas usuarias.

## Decisión

Una clave por cliente (`API_KEYS`), exigida en `X-API-Key` para `/ask` y `/metrics`, comparada en tiempo constante;
el nombre del cliente, nunca la clave, va a log, auditoría y trazas. Límite de peticiones por cliente por minuto con
reloj inyectado y `Retry-After`. Con `ENVIRONMENT=production`, `config`/`compliance` impiden arrancar si el modelo es
`fake`, faltan claves o son cortas, o las trazas no ocultan entradas y salidas. Secretos solo en el entorno de Render.

## Consecuencias

- Una configuración insegura falla al desplegar, no en producción; el health check de Render lo hace visible.
- Los logs y trazas no contienen pregunta, respuesta ni clave; diagnosticar requiere el `request_id`.
- `doc/compliance-checklist.md` mapea cada regla a su código y a su prueba.
