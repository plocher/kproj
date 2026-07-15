Feature: kproj flushes no-push batch commits (kproj#44)
  As a project author batching site publishes
  I want a final plain invocation to flush queued site commits
  So that the site repository is not left ahead of its upstream.

  Scenario: a no-push batch commit is flushed by the next unchanged plain run
    Given a populated KiCad project with status active
    And a clean site repo
    When I run kproj
    Then a site commit was made without a push
    When I run plain kproj with unchanged content
    Then pending site commits were pushed

  Scenario: an unchanged plain run with no debt remains quiet
    Given a populated KiCad project with status active
    And a clean site repo
    And push is enabled
    And the site repo has 0 pending commits
    And the project content is unchanged
    When I run kproj
    Then the unchanged no-op is quiet

  Scenario: no-push reports pending site commit debt without pushing
    Given a populated KiCad project with status active
    And a clean site repo
    And no_push mode is active
    And the site repo has 2 pending commits
    And the project content is unchanged
    When I run kproj
    Then no git push was invoked
    And pending site commit debt is reported for "--no-push"

  Scenario: dry-run reports pending site commit debt without pushing
    Given a populated KiCad project with status active
    And a clean site repo
    And push is enabled
    And the site repo has 2 pending commits
    When I run kproj with --dry-run
    Then no git push was invoked
    And pending site commit debt is reported for "dry-run"

  Scenario: an unavailable upstream is an exit-neutral advisory
    Given a populated KiCad project with status active
    And no findings except the GitHub-link advisory
    And a clean site repo
    And push is enabled
    And the site repo upstream is unavailable
    And the project content is unchanged
    When I run kproj
    Then the unavailable upstream advisory is reported
    And kproj exits with code 0
