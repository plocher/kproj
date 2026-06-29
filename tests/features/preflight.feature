Feature: kproj pre-flight walks the project resolver and kicad-cli locator
  As a project author
  I want kproj to fail fast when my environment is misconfigured
  So that I see a clear error rather than a surprise mid-pipeline.

  # Foundation walking-skeleton: only pre-flight is implemented; downstream
  # steps are stubs that return outcome=failed/exit_code=2. Full per-story
  # feature coverage lands in the slices that implement those services.

  Scenario: kproj refuses to publish when the project cannot be resolved
    Given a directory with no .kicad_pro file
    When I run kproj against that directory
    Then kproj exits with code 2
    And stderr mentions "project resolution failed"
