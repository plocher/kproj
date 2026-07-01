Feature: kproj finds the project without a full path (PRD Story 3)
  As a project author
  I want kproj to find my project without typing a full path
  So that I can publish from anywhere convenient.

  # Note: The full project-resolution story (including basename resolution
  # from ~/Dropbox/KiCad/projects/) is covered by the KicadProjectReader
  # unit tests. The Behave scenario here validates the end-to-end workflow
  # resolves a project given a directory path.

  Scenario: Story 3 — kproj resolves a project from its directory path
    Given a populated KiCad project with status active
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page exists in the site repo

  Scenario: Story 3 — kproj fails cleanly when no .kicad_pro file is found
    Given a directory with no .kicad_pro file
    When I run kproj against that directory
    Then kproj exits with code 2
    And stderr mentions "project resolution failed"
