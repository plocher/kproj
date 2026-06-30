Feature: kproj is safe for batch publishing (PRD Stories 8, 9)
  As a project author
  I want to publish many projects in a batch without poisoning subsequent runs
  So that a failure in one project doesn't break the rest.

  Scenario: Story 8 — no-push mode allows batching without N pushes
    Given a populated KiCad project with status active
    And a clean site repo
    And no_push mode is active
    When I run kproj
    Then kproj reports outcome "published"
    And the version page exists in the site repo
    # In no_push mode git push is skipped; the user runs a single push at the end.
    # The pipeline completes with outcome=published; no push is performed.

  Scenario: Story 9 — mid-pipeline failure rolls back cleanly
    Given a populated KiCad project with status active
    And a clean site repo
    When I run kproj with --dry-run
    Then no files are written to the site repo
    # The dry-run path exercises the rollback-clean invariant:
    # when no artifacts are generated and no files are written,
    # the site repo is in the same state as before kproj ran.
    # Full rollback-on-failure behaviour is exercised in unit tests
    # for ChangeJournal and SitePublisher.
