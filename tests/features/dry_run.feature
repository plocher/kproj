Feature: kproj --dry-run previews without writing (PRD Story 2)
  As a project author
  I want to preview what kproj would publish without actually publishing
  So that I can verify my project is ready.

  Scenario: Story 2 — dry-run does not write files or perform git operations
    Given a populated KiCad project with status active
    And a clean site repo
    When I run kproj with --dry-run
    Then no files are written to the site repo
