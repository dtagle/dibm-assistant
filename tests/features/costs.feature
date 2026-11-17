Feature: Cheaper answers with the same quality
  Each answer says which model it used, why, and how much it cost.
  A rule in code routes each question to the small or the large model.

  Scenario: A simple question goes to the small model and reports its cost
    Given the priced assistant is running
    When I ask the priced assistant "¿Cuáles son las últimas publicaciones?"
    Then the answer used the small model because of "short_question"
    And the cost matches the tokens of the small model
    And no call was cached

  Scenario: A question that asks for analysis goes to the large model
    Given the priced assistant is running
    When I ask the priced assistant "Compara las publicaciones de Pérez"
    Then the answer used the large model because of "keyword"
    And the cost matches the tokens of the large model

  Scenario: A question longer than the router limit goes to the large model
    Given the priced assistant is running with "ROUTER_MAX_CHARS" set to "20"
    When I ask the priced assistant "Quiero los documentos de Pérez"
    Then the answer used the large model because of "long_question"

  Scenario: With routing turned off every question goes to the large model
    Given the priced assistant is running with "ROUTING" set to "false"
    When I ask the priced assistant "¿Cuáles son las últimas publicaciones?"
    Then the answer used the large model because of "routing_disabled"

  Scenario: The metrics add up the cost of every answer
    Given the priced assistant is running
    When I ask the priced assistant "¿Cuáles son las últimas publicaciones?"
    And I ask the priced assistant "Compara las publicaciones de Pérez"
    Then the metrics cost is the sum of both answers

  Scenario: A real model that fails gives a 502 with the request id
    Given the priced assistant is running with a model that is unavailable
    When I send request "req-502" to the priced assistant asking "¿Cuáles son las últimas publicaciones?"
    Then the response is model unavailable for request "req-502"

  Scenario: The gateway provider refuses to start without Cloudflare credentials
    When I load the settings for the gateway provider without "CF_ACCOUNT_ID"
    Then startup fails naming "CF_ACCOUNT_ID"
