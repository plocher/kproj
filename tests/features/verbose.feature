Feature: kproj -v surfaces findings on stderr (PRD Story 12)
  As a project author when something goes wrong
  I want kproj -v to surface findings on stderr
  So that I can understand what needs attention without opening the version page.

  # Wave-3 M11 rewrite: pre-fix this scenario never passed -v and asserted
  # only that publishing succeeded, so the user-facing diagnostic contract
  # was un-tested and unimplemented.  Post-fix (BLOCKER 4) findings are
  # rendered to stderr via StderrFormatter after every workflow run.  The
  # rewrite invokes kproj with -v against a project with audit warnings
  # and asserts the finding text lands in stderr in the user's vocabulary.

  Scenario: Story 12 — verbose kproj surfaces audit findings on stderr
    Given a project with audit warnings
    And a clean site repo
    When I run kproj with -v
    Then kproj reports outcome "published"
    And stderr contains the audit finding names
    And kproj exit code signals findings present
