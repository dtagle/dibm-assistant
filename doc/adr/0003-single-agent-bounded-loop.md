# 0003 Un solo agente con bucle con tope y protocolo JSON

## Contexto

Las preguntas se resuelven con una o dos consultas al catálogo. Varios agentes o un bucle sin límite agregarían
costo y comportamientos difíciles de probar.

## Decisión

Un solo agente con cuatro herramientas de solo lectura. El modelo responde un objeto JSON: `{"tool", "args"}` o
`{"answer"}`. El resultado de la herramienta vuelve como mensaje `user` con el prefijo
`Resultado de la herramienta: `. El bucle se corta en `AGENT_MAX_STEPS` con un mensaje fijo. Una salida que no es
JSON válido se trata como `answer`.

## Consecuencias

- Costo y latencia acotados por diseño; cada llamada a herramienta queda en un evento `audit`.
- Preguntas complejas pueden agotar el tope; la persona recibe una indicación de concretar.
- Herramientas desconocidas o argumentos inválidos se devuelven al modelo como resultado de error, no como 500.
