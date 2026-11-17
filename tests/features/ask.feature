Feature: Ask the DIBM Assistant about Banxico research documents
  Analysts ask questions in Spanish and the assistant answers from the snapshot,
  citing the page of each document.

  Scenario: Asking for a publication by id cites its source
    Given the assistant is running with the sample catalog
    When I ask "¿De qué trata el documento 2025-12?"
    Then the response status is 200
    And the tools used are "get_publication"
    And the agent took 2 steps
    And the answer mentions "Inflación y expectativas en México"
    And the answer mentions "visor.html?clave=2025-12"

  Scenario: An unknown publication is reported
    Given the assistant is running with the sample catalog
    When I ask "¿De qué trata el documento 1900-99?"
    Then the response status is 200
    And the tools used are "get_publication"
    And the answer mentions "1900-99"
    And the answer mentions no sample title

  Scenario: Asking for an author by surname without accents
    Given the assistant is running with the sample catalog
    When I ask "¿Qué ha publicado perez?"
    Then the tools used are "search_by_author"
    And the answer mentions "Inflación y expectativas en México"
    And the answer mentions "Política monetaria y tipo de cambio"
    And the answer does not mention "Mercado laboral y salarios"

  Scenario: The latest publications come from the newest year of the snapshot
    Given the assistant is running with the sample catalog
    When I ask "¿Cuáles son las últimas publicaciones?"
    Then the tools used are "latest_publications"
    And the answer mentions "Inflación y expectativas en México"
    And the answer mentions "Mercado laboral y salarios"
    And the answer does not mention "Política monetaria y tipo de cambio"

  Scenario: The latest publications of a given year
    Given the assistant is running with the sample catalog
    When I ask "Publicaciones de 2024"
    Then the tools used are "latest_publications"
    And the answer mentions "Política monetaria y tipo de cambio"
    And the answer does not mention "Inflación y expectativas en México"

  Scenario: Searching publications by topic
    Given the assistant is running with the sample catalog
    When I ask "¿Qué hay sobre salarios?"
    Then the tools used are "search_publications"
    And the answer mentions "Mercado laboral y salarios"
    And the answer does not mention "Notas sobre la balanza de pagos"

  Scenario: A question without a known intent gets the help message
    Given the assistant is running with the sample catalog
    When I ask "Hola"
    Then the response status is 200
    And the answer is "Pregúntame por un autor o por las últimas publicaciones del DIBM."
    And no tools were used

  Scenario Outline: Empty or too long questions are rejected
    Given the assistant is running with the sample catalog
    When I ask a question of <length> characters
    Then the response status is 422

    Examples:
      | length |
      | 0      |
      | 2001   |

  Scenario: The step cap stops the agent loop
    Given the assistant is running with the sample catalog and at most 1 agent step
    When I ask "¿Cuáles son las últimas publicaciones?"
    Then the response status is 200
    And the agent took 1 steps
    And the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."
