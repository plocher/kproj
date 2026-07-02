Feature: kproj publishes a KiCad project to the site repo (PRD Story 1)
  As a project author
  I want to publish my project's current state to the SPCoast site
  So that I can share the design without manual file copying.

  # iBOM caveat (kproj#10): iBOM end-to-end is gated on a separate spike.
  # The artifact generator is stubbed here with placeholder files to test
  # pipeline orchestration without invoking real iBOM.

  # Stories 14-18 (visitor/consumer-facing) cross the Jekyll build and are
  # not Behave-testable within kproj alone. They are Phase 7 manual-validation
  # scenarios against the live SPCoast site.

  Scenario: Story 1 — publish a project to the site repo
    Given a populated KiCad project with status active
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page exists in the site repo
    And the project page exists in the site repo
    And a new commit was added to the site repo

  # Stories 14-18 (visitor/consumer-facing): Phase 7 manual validation.
  # See docs/PRD.md § Stories 14-18 for acceptance criteria.
