Feature: Safe production access
  Only clients with an API key can ask questions, each client has a
  request limit, and production refuses to start with unsafe settings.

  Scenario: Asking without an API key is rejected
    Given the secured assistant is running
    When I ask "¿Cuáles son las últimas publicaciones?" without an API key
    Then the response status is 401
    And the response detail is "invalid or missing API key"

  Scenario: Asking with a wrong API key is rejected
    Given the secured assistant is running
    When I ask "¿Cuáles son las últimas publicaciones?" with the API key "wrong-key-0123456789"
    Then the response status is 401
    And the response detail is "invalid or missing API key"

  Scenario: Reading the metrics needs an API key
    Given the secured assistant is running
    When I read "/metrics" without an API key
    Then the response status is 401

  Scenario: A valid API key gets an answer
    Given the secured assistant is running
    When I ask "¿Cuáles son las últimas publicaciones?" with the valid API key
    Then the response status is 200

  Scenario Outline: Public pages need no API key
    Given the secured assistant is running
    When I read "<path>" without an API key
    Then the response status is 200

    Examples:
      | path    |
      | /       |
      | /health |
      | /docs   |

  Scenario: Too many questions in a minute are limited
    Given the secured assistant is running with a limit of 2 requests per minute
    When I ask "Hola" 3 times with the valid API key
    Then the last response status is 429
    And the last response detail is "rate limit exceeded"
    And the last response asks to retry after 60 seconds

  Scenario: The limit resets after a minute
    Given the secured assistant is running with a limit of 1 requests per minute
    When I ask "Hola" 1 times with the valid API key
    And 61 seconds pass
    And I ask "Hola" 1 times with the valid API key
    Then the last response status is 200

  Scenario: Each client has its own limit
    Given the secured assistant is running with two clients and a limit of 1 requests per minute
    When the first client asks "Hola"
    And the second client asks "Hola"
    Then the last response status is 200

  Scenario Outline: Production refuses to start with unsafe settings
    Given a production configuration that is otherwise safe
    And "<variable>" is set to "<value>"
    When the assistant starts
    Then it refuses to start

    Examples:
      | variable       | value                         |
      | MODEL_PROVIDER | fake                          |
      | API_KEYS       |                               |
      | API_KEYS       | dibm-portal:short-key-15chr   |
      | HIDE_INPUTS    | false                         |
      | HIDE_OUTPUTS   | false                         |

  Scenario: Production starts with safe settings
    Given a production configuration that is otherwise safe
    When the assistant starts
    Then it starts
