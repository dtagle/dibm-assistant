# 0002 Snapshot del DIBM en lugar de consultar el sitio en vivo

## Contexto

Las preguntas son sobre los Documentos de Investigación de Banxico. Consultar el sitio en cada pregunta agrega
latencia, dependencia de un tercero, carga al sitio y resultados que cambian entre pruebas.

## Decisión

El producto lee `data/publications.json`, un snapshot generado por una persona con `scripts/ingest_dibm.py`, una
sola vez al arrancar. Para actualizar se regenera y se vuelve a copiar el archivo. Si falta o está vacío, no arranca.

## Consecuencias

- Respuestas rápidas, deterministas y sin red; las herramientas son de solo lectura.
- El conocimiento puede quedar desactualizado hasta la siguiente ingesta; «más recientes» significa del snapshot.
- Los datos vienen de un sitio externo y se tratan como no confiables (la página pinta con `textContent`).
- Las pruebas usan un catálogo fixture propio para no romperse al actualizar el snapshot.
