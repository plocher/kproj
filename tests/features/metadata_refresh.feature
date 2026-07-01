Feature: kproj refreshes metadata without regenerating artifacts (PRD Story 6)
  As a project author
  I want to update a release's status without re-generating renders/fab/etc.
  So that status transitions are cheap.

  # Wave-3 M11 rewrite: pre-fix this scenario ran the same project twice
  # and asserted 'noop' — not a real experimental→active refresh.  The
  # rewrite mutates COMMENT9 between the two runs so the pipeline actually
  # exercises the metadata-refresh path in PRD Story 6's user vocabulary.

  Scenario: Story 6 — flipping status from experimental to active triggers a refresh
    Given a populated KiCad project with status experimental
    And a clean site repo
    And the project was previously published
    When I change the project status to active
    And I run kproj a second time with the same project
    Then kproj reports outcome "refreshed"
    And the version page has updated status
    And the kproj outcome is not a full publish
