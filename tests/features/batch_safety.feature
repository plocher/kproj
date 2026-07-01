Feature: kproj is safe for batch publishing (PRD Stories 8, 9)
  As a project author
  I want to publish many projects in a batch without poisoning subsequent runs
  So that a failure in one project doesn't break the rest.

  Scenario: Story 8 — no-push mode allows batching without a push per project
    Given a populated KiCad project with status active
    And a clean site repo
    And no_push mode is active
    When I run kproj
    Then kproj reports outcome "published"
    And the version page exists in the site repo
    And no git push was invoked

  # Wave-3 M11 rewrite: Story 9 previously ran --dry-run and asserted
  # "no files written" — that exercised the dry-run path, not the
  # mid-pipeline-failure rollback contract.  The rewrite injects a
  # failing artifact producer AFTER an earlier producer has already
  # written an asset, then asserts the site repo is restored to its
  # pre-kproj state (site_repo/versions/... is gone; version page
  # was never committed).

  Scenario: Story 9 — mid-pipeline artifact failure rolls back all writes
    Given a populated KiCad project with status active
    And a clean site repo
    And an artifact producer will fail after writing one asset
    When I run kproj
    Then kproj reports outcome "failed"
    And kproj exits with code 2
    And no partial files remain in the site repo
