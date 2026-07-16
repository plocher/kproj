Feature: kproj -v reports compact findings summaries on stderr (PRD Story 12)
  As a project author when something goes wrong
  I want kproj -v to report concise findings context
  So that terminal output stays focused on publish status while details remain in the report artifacts.

  # Stderr policy: -v keeps runtime output concise with aggregate findings
  # context; detailed finding rows are emitted only with -d.

  Scenario: Story 12 — verbose kproj shows compact findings context
    Given a project with audit warnings
    And a clean site repo
    When I run kproj with -v
    Then kproj reports outcome "published"
    And stderr reports a compact findings summary
    And kproj exit code signals findings present
