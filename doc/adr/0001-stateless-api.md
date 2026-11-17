# 0001 API sin estado

## Contexto

El DIBM Assistant debe escalar corriendo más copias detrás de Render, sin base de datos ni sesiones.

## Decisión

La API no guarda conversaciones: el navegador conserva el historial y lo manda en `history` en cada `POST /ask`.
Solo se mantiene en memoria, por proceso, lo que no es de la persona usuaria: métricas de `/metrics` y contadores
del límite de peticiones.

## Consecuencias

- Escalar es correr más copias; cualquier copia atiende cualquier petición.
- El historial viaja en cada petición; la ventana `HISTORY_WINDOW` acota su costo.
- Métricas y límite de peticiones son por proceso (`pid` en `/health` y `/metrics`); con varias copias, el límite
  efectivo por cliente se multiplica. Se acepta para el plan gratuito de una copia.
