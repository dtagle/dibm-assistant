Feature: Trace and measure every request
  Support staff can answer "what happened with request X?" with data:
  every response carries a request id and the process reports its metrics.

  Scenario: A request without an id gets a generated one
    Given the observed assistant is running
    When I check the health of the assistant
    Then the response carries a generated request id

  Scenario: The client request id is kept in the header and the body
    Given the observed assistant is running
    When I ask "¿Cuáles son las últimas publicaciones?" with request id "demo-123"
    Then the response header "X-Request-ID" is "demo-123"
    And the response body request id is "demo-123"

  Scenario: Metrics count the requests and the tokens of this process
    Given the observed assistant is running
    When I ask "¿Cuáles son las últimas publicaciones?" 2 times
    And I read the metrics
    Then the metrics report 2 requests
    And the metrics report the input and output tokens of those answers

  Scenario: The latency SLO is met when answers are fast
    Given the observed assistant is running with an SLO of 2000 ms
    And each model call takes 0.5 seconds
    When I ask "¿Cuáles son las últimas publicaciones?" 1 times
    And I read the metrics
    Then the latency p95 is 1000 ms
    And the SLO is met

  Scenario: The latency SLO is missed when answers are slow
    Given the observed assistant is running with an SLO of 2000 ms
    And each model call takes 1.5 seconds
    When I ask "¿Cuáles son las últimas publicaciones?" 1 times
    And I read the metrics
    Then the latency p95 is 3000 ms
    And the SLO is not met

  Scenario: An unexpected failure answers 500 with the request id
    Given the observed assistant is running with a model that fails
    When I ask "¿Cuáles son las últimas publicaciones?" with request id "fail-42"
    Then the response status is 500
    And the response body is an internal error for request "fail-42"
    And the response header "X-Request-ID" is "fail-42"
