Feature: kproj treats kicad-cli DRC/ERC crashes as mechanical failures (ADR 0004)
  As a project author
  I want kicad-cli crashes to surface as clear mechanical failures with exit 2
  So that a broken DRC/ERC toolchain never quietly publishes a release.

  # Wave-3 M4 round-2 rewrite: pre-fix, a kicad-cli DRC/ERC crash that
  # produced no JSON was modelled as an ordinary error :class:`Finding`,
  # so ``compute_exit_code`` mapped a mechanical failure to
  # ``exit=1`` ("findings present, publish succeeded") instead of
  # ``exit=2`` ("mechanical failure").  ADR 0004 requires mechanical
  # failures to have a separate channel from findings; DesignAnalyzer
  # raises :class:`DesignAnalysisError`, PublishWorkflow catches it
  # before opening the change journal, and returns
  # ``PublishResult(outcome="failed", exit_code=2)``.

  Scenario: DRC mechanical crash (nonzero + no JSON) fails with exit 2
    Given a populated KiCad project with status active
    And a clean site repo
    And kicad-cli DRC will crash without producing JSON
    When I run kproj
    Then kproj reports outcome "failed"
    And the kproj exit code is 2
    And no version page is written
    And no git commit is invoked

  Scenario: ERC mechanical crash (nonzero + no JSON) fails with exit 2
    Given a populated KiCad project with status active
    And a clean site repo
    And kicad-cli ERC will crash without producing JSON
    When I run kproj
    Then kproj reports outcome "failed"
    And the kproj exit code is 2
    And no version page is written
    And no git commit is invoked
