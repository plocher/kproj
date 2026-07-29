Feature: kproj -v shows findings detail on stderr (PRD Story 12)
  As a project author when something goes wrong
  I want kproj -v to report per-finding detail inline
  So that I can see what failed without digging into report artifacts.

  # Stderr policy: -v shows DRC/ERC findings inline right after analysis
  # and emits non-design (audit) findings in the end-of-run block.
  # -d shows the exec-transcript (shell-style √/? lines) for each subprocess.

  Scenario: Story 12 — verbose kproj shows per-finding detail on stderr
    Given a project with audit warnings
    And a clean site repo
    When I run kproj with -v
    Then kproj reports outcome "published"
    And stderr reports findings detail and a summary
    And kproj exit code signals findings present
