Feature: kproj skips site writes for private projects (PRD Story 7)
  As a project author with a project marked ${COMMENT9} = private
  I want kproj to run the audit + DRC/ERC for stderr but not publish
  So that private designs never end up on the public site by accident.

  # Wave-2 wires DESIGN steps 2-4 (read + analyze + status detection).
  # The exit-code is finding-driven: a clean private project exits 0;
  # one with audit warnings (production_missing, etc.) still exits 1
  # under the surface-not-block policy from ADR 0004.

  Scenario: a private project short-circuits before site writes
    Given a KiCad project whose schematic COMMENT9 is "private"
    When I run kproj against that project
    Then kproj reports outcome "private-skip"
    And stderr mentions "status=private"
