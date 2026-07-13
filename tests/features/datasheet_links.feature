Feature: kproj publishes datasheet deep-links from the BOM's Datasheet Name (kproj#29)
  As a project author
  I want curated components to link straight to their datasheet in the shared library
  So that visitors can view/download the datasheet without me copying PDFs into the site

  # The `jbom bom` invocation is faked (tests/features/steps/publish_steps.py's
  # _default_fake_datasheet_lookup) so these scenarios never exec a real jBOM
  # subprocess or touch the network - per ADR 0011's advisory-only, never-blocking
  # contract.

  Scenario: A curated component's Datasheet Name becomes a view + download link
    Given a populated KiCad project with status active
    And a clean site repo
    And jbom reports the datasheet name "yageo_rc0805_resistor" for this project
    When I run kproj
    Then kproj reports outcome "published"
    And the project page links the datasheet "yageo_rc0805_resistor" for view and download

  Scenario: An uncurated project publishes without any datasheet link
    Given a populated KiCad project with status active
    And a clean site repo
    And jbom reports no datasheet names for this project
    When I run kproj
    Then kproj reports outcome "published"
    And the project page has no datasheet links

  Scenario: jbom too old to know the Datasheet Name field degrades gracefully
    Given a populated KiCad project with status active
    And a clean site repo
    And jbom is too old to recognize the Datasheet Name field
    When I run kproj
    Then kproj reports outcome "published"
    And the project page has no datasheet links
    And kproj exit code signals findings present
