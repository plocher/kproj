Feature: kproj publishes a "see/fork on GitHub" link (kproj#30)
  As a project author whose KiCad project directory is its own git repo
  I want kproj to surface a GitHub link when the current state is pushed
  So that site visitors can view or fork the source, without ever
  breaking a publish when the project isn't a pushed GitHub repo.

  # Detection is local-git-metadata-only (no `git fetch` / network call);
  # "pushed" is simulated in these scenarios by seeding local refs the
  # same way a real `git push -u origin <branch>` would leave them.

  Scenario: a project with a pushed GitHub remote gets a GitHub link
    Given a populated KiCad project with status active
    And the project directory is a git repo with a pushed GitHub remote
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter includes the GitHub link

  Scenario: a project that is not a git repo gets no GitHub link
    Given a populated KiCad project with status active
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link

  Scenario: a project with a GitHub remote but no upstream tracking gets no GitHub link
    Given a populated KiCad project with status active
    And the project directory is a git repo with a GitHub remote but no upstream tracking
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link

  Scenario: a project with local commits ahead of the pushed upstream gets no GitHub link
    Given a populated KiCad project with status active
    And the project directory is a git repo with a GitHub remote but local commits ahead of upstream
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link

  Scenario: a project checked out in detached HEAD state gets no GitHub link
    Given a populated KiCad project with status active
    And the project directory is a git repo with a pushed GitHub remote but checked out detached
    And a clean site repo
    When I run kproj
    Then kproj reports outcome "published"
    And the version page front-matter has no GitHub link
