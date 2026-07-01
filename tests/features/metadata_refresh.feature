Feature: kproj refreshes metadata without regenerating artifacts (PRD Story 6)
  As a project author
  I want to update a release's status without re-generating renders/fab/etc.
  So that status transitions are cheap.

  # Wave-3 M11 round-2 rewrite (user framing):
  #   GIVEN a project that has been published once by kproj
  #         (so baseline _versions/<P>/<R>.md, pages/<P>.md, and all
  #          assets exist on disk with realistic mtimes)
  #   WHEN the SCH's ${COMMENT9} value changes to <new-status>
  #        (real edit; no manual mtime-touching)
  #   THEN the outcome should be "refreshed" (metadata-only change,
  #        no artifact regen) per PRD Story 6
  #   AND  _versions/<P>/<R>.md front-matter's status field reflects
  #        <new-status>
  #   AND  assets are NOT regenerated (mtimes unchanged from baseline)
  #   AND  the site repo is committed with the `refresh:` message prefix
  #
  # Pre-round-2 the scenario bumped asset mtimes to trick the M1
  # freshness rule.  Round-2 removes that workaround; instead the code
  # side compares content-hashes (title-block stripped) to distinguish
  # metadata-only edits from schematic-content edits.

  Scenario: Story 6 — experimental → active is a metadata refresh
    Given a populated KiCad project with status experimental
    And a clean site repo
    And the project was previously published
    When I change COMMENT9 in the schematic to "active"
    And I run kproj a second time with the same project
    Then kproj reports outcome "refreshed"
    And the version page front-matter status is "active"
    And assets are not regenerated
    And a git commit with the "refresh:" prefix was invoked

  Scenario: Story 6 — active → broken is a metadata refresh
    Given a populated KiCad project with status active
    And a clean site repo
    And the project was previously published
    When I change COMMENT9 in the schematic to "broken"
    And I run kproj a second time with the same project
    Then kproj reports outcome "refreshed"
    And the version page front-matter status is "broken"
    And assets are not regenerated
    And a git commit with the "refresh:" prefix was invoked

  Scenario: Story 6 — active → retired is a metadata refresh
    Given a populated KiCad project with status active
    And a clean site repo
    And the project was previously published
    When I change COMMENT9 in the schematic to "retired"
    And I run kproj a second time with the same project
    Then kproj reports outcome "refreshed"
    And the version page front-matter status is "retired"
    And assets are not regenerated
    And a git commit with the "refresh:" prefix was invoked

  Scenario: Story 6 — active → replaced-by:<other> is a metadata refresh
    Given a populated KiCad project with status active
    And a clean site repo
    And the project was previously published
    When I change COMMENT9 in the schematic to "replaced-by:NewProject"
    And I run kproj a second time with the same project
    Then kproj reports outcome "refreshed"
    And the version page front-matter status is "replaced-by"
    And assets are not regenerated
    And a git commit with the "refresh:" prefix was invoked

  # Story 7 policy: private status skips publish but audit + DRC/ERC
  # still run.  Combined with round-2 M4: a private-skip returns cleanly
  # (exit 0 or 1 depending on findings), never invokes a publish or
  # refresh, and never opens the change journal.
  Scenario: Story 7 — active → private is a private-skip (no publish, no refresh)
    Given a populated KiCad project with status active
    And a clean site repo
    And the project was previously published
    When I change COMMENT9 in the schematic to "private"
    And I run kproj a second time with the same project
    Then kproj reports outcome "private-skip"
    And assets are not regenerated
    And no git commit is invoked on the second run

  # Corner case: erasing COMMENT9 makes the field "missing", which
  # fires the ``comment9_missing`` audit warning even though the
  # resolved status still defaults to ``active``.  The extra finding
  # changes the audit-count block, so the outcome is a refresh (not a
  # noop) — still no artifact regeneration, per PRD Story 6.
  Scenario: Story 6 — active → empty (defaults to active) is a refresh
    Given a populated KiCad project with status active
    And a clean site repo
    And the project was previously published
    When I change COMMENT9 in the schematic to ""
    And I run kproj a second time with the same project
    Then kproj reports outcome "refreshed"
    And the version page front-matter status is "active"
    And assets are not regenerated
