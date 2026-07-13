Feature: kproj publishes a "see/fork on GitHub" link (kproj#30)
  As a project author whose KiCad project directory is its own git repo
  I want kproj to surface a GitHub link when the current state is pushed,
  and to actively advise me when it can't, without ever breaking a
  publish when the project isn't a pushed GitHub repo.

  # Detection is local-git-metadata-only (no `git fetch` / network call);
  # "pushed" is simulated in these scenarios by seeding local refs the
  # same way a real `git push -u origin <branch>` would leave them.
  #
  # Absence-highlighting (clarified requirement): the old EAGLE-era site
  # linked every project to its GitHub repo, so kproj advises - via a
  # non-fatal Metadata Audit finding, publish still succeeds - whenever
  # that backing is missing or not confirmed pushed.

  Scenario: a project with a pushed GitHub remote gets a GitHub link and no advisory
    Given a populated KiCad project with status active
    And the project directory is a git repo with a pushed GitHub remote
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter includes the GitHub link
    And the version page body has no github-link advisory finding

  Scenario: a project that is not a git repo gets no GitHub link and a missing-backing advisory
    Given a populated KiCad project with status active
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link
    And the version page body has a github_link_missing advisory finding

  Scenario: a project with a GitHub remote but no upstream tracking gets no GitHub link and an unpushed advisory
    Given a populated KiCad project with status active
    And the project directory is a git repo with a GitHub remote but no upstream tracking
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link
    And the version page body has a github_link_unpushed advisory finding

  Scenario: a project with local commits ahead of the pushed upstream gets no GitHub link and an unpushed advisory
    Given a populated KiCad project with status active
    And the project directory is a git repo with a GitHub remote but local commits ahead of upstream
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link
    And the version page body has a github_link_unpushed advisory finding

  Scenario: a project checked out in detached HEAD state gets no GitHub link and an unpushed advisory
    Given a populated KiCad project with status active
    And the project directory is a git repo with a pushed GitHub remote but checked out detached
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link
    And the version page body has a github_link_unpushed advisory finding

  Scenario: a project whose history has diverged from the pushed upstream gets no GitHub link and an unpushed advisory
    Given a populated KiCad project with status active
    And the project directory is a git repo whose history has diverged from the pushed upstream
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link
    And the version page body has a github_link_unpushed advisory finding
