Feature: kproj surfaces findings honestly on the version page (PRD Stories 4, 5)
  As a project author
  I want kproj to publish even when my project has audit warnings
  So that I can iterate against the published findings.

  Scenario: Story 4 — publish proceeds despite audit warnings; exit code 1
    Given a project with audit warnings
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And kproj exit code signals findings present

  Scenario: Story 5 — version page body shows audit + DRC/ERC tables
    Given a project with audit warnings
    And a clean site repo
    When I run kproj
    Then the version page exists in the site repo
    And the version page contains the audit findings table
    And the version page front-matter includes findings counts
