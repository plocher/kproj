Feature: kproj flushes no-push batch commits (kproj#44)
  As a project author batching site publishes
  I want a final plain invocation to flush queued site commits
  So that the site repository is not left ahead of its upstream.

  Scenario: an unchanged plain run flushes pending site commits
    Given a populated KiCad project with status active
    And a clean site repo
    And push is enabled
    And the site repo has 2 pending commits
    And the project content is unchanged
    When I run kproj
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
