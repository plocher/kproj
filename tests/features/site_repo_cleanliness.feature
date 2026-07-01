Feature: kproj refuses to publish to a dirty site repo (PRD Story 10)
  As a project author
  I want kproj to refuse if the site repo has uncommitted edits
  So that my hand-edits don't entangle with kproj's commit.

  Scenario: Story 10 — dirty site repo fails preflight before any writes
    Given a populated KiCad project with status active
    And a clean site repo
    And the site repo has uncommitted changes
    When I run kproj
    Then kproj reports outcome "failed"
    And kproj exits with code 2
    And stderr explains the uncommitted state
