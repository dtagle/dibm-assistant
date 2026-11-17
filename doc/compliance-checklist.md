# Checklist de compliance

Con `ENVIRONMENT=production` el producto revisa estas reglas al arrancar (al importar `app.main` y en
`create_app()`). Si alguna falla, no arranca: el error nombra cada regla que falla y nunca muestra una clave.
Fuera de producción las reglas de esta tabla no se aplican; las de formato de `API_KEYS` sí, en todo ambiente.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción `MODEL_PROVIDER` no puede ser `fake` | `app/compliance.py`, `_model_rule` | `tests/test_production_config.py` (`test_compliance_error_names_every_failed_rule_without_the_keys`); contrato `test_production_refuses_the_fake_model` |
| En producción `API_KEYS` no puede estar vacía | `app/compliance.py`, `_api_keys_rule` | `tests/test_production_config.py`; el error dice `API_KEYS must not be empty` |
| En producción cada clave tiene 16 caracteres o más | `app/compliance.py`, `_api_keys_rule` (`MIN_API_KEY_CHARS`) | `tests/test_production_config.py` (`test_a_key_of_sixteen_characters_is_long_enough_for_production`) |
| Con trazas encendidas, `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` | `app/compliance.py`, `_tracing_rule` | `tests/test_production_config.py` (`test_hidden_trace_rules_apply_only_when_tracing_is_on`) |
| `API_KEYS` mal formada impide arrancar; el error da la posición y el largo, nunca el valor | `app/config.py`, `_api_keys` | `tests/test_production_config.py` (`test_malformed_api_keys_entry_is_reported_by_position_and_length`); contrato `test_a_broken_api_keys_never_leaks_the_key` |
| Las claves no salen en `repr` de la configuración | `app/config.py`, `Settings.api_keys` (`repr=False`) | `tests/test_production_config.py` (`test_api_keys_are_hidden_from_the_settings_repr`) |
| `POST /ask` y `GET /metrics` exigen `X-API-Key`; la clave se compara con `hmac.compare_digest` | `app/security.py`, `authenticate`; `app/main.py`, `_client_dependency` | Contrato `test_asking_without_a_key_returns_401` y `test_asking_with_a_wrong_key_returns_401` |
| La clave nunca sale en el log, la traza ni la respuesta; solo el nombre del cliente | `app/main.py` (`client` en `audit`, `agent_run` y traza); `app/tracing.py`, `Tracer.wrap` | `tests/test_security.py` (`test_client_name_is_logged_in_runs_and_audits_but_the_key_never_is`, `test_rejected_key_is_not_echoed_in_the_response_or_the_log`, `test_trace_metadata_carries_the_client_name`) |
| Límite de peticiones por cliente con `Retry-After`, usando el reloj inyectado | `app/security.py`, `RateLimiter` | `tests/test_security.py` (`test_retry_after_counts_the_seconds_left_in_the_minute`); contrato `test_too_many_requests_returns_429_with_retry_after` |
| La página guarda la clave en `sessionStorage`, nunca en el almacenamiento permanente ni en el código | `app/static/index.html` | `tests/test_security.py` (`test_home_page_keeps_the_key_in_session_storage_and_sends_it_as_a_header`) |

Para revisar todo de una vez, desde `product/`:

```bash
pytest tests/test_production_config.py tests/test_security.py
```
