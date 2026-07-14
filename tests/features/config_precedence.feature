Feature: kproj CLI/env/yaml configuration precedence (kproj#37)
  As a kproj user
  I want CLI flags to override KPROJ_* environment variables, and those to
  override ~/.kproj.yaml, for the datasheet-related settings
  So that I can configure kproj at whichever layer is most convenient

  # These scenarios drive kproj.cli.main with real argv, real environment
  # variables, and a real ~/.kproj.yaml fixture file - never a hand-built
  # KprojConfig - so the CLI > env > yaml precedence chain (kproj#37) is
  # exercised end-to-end, not just at the config-resolver unit level.
  # PublishWorkflow is stubbed (no kicad-cli / jbom / git needed) purely to
  # capture the resolved KprojConfig for assertion.

  Scenario Outline: A CLI flag overrides both the environment variable and ~/.kproj.yaml
    Given a ~/.kproj.yaml with "<yaml_key>" set to "from-yaml"
    And the environment variable "<env_var>" is set to "from-env"
    When I run kproj with "<cli_flag>" set to "from-cli"
    Then the resolved "<config_field>" is "from-cli"

    Examples: datasheet-related flags
      | yaml_key          | env_var                 | cli_flag             | config_field      |
      | inventory         | KPROJ_INVENTORY         | --inventory          | inventory         |
      | datasheet_library | KPROJ_DATASHEET_LIBRARY | --datasheet-library  | datasheet_library |
      | datasheet_repo    | KPROJ_DATASHEET_REPO    | --datasheet-repo     | datasheet_repo    |

  Scenario Outline: A KPROJ_* environment variable overrides ~/.kproj.yaml when no CLI flag is given
    Given a ~/.kproj.yaml with "<yaml_key>" set to "from-yaml"
    And the environment variable "<env_var>" is set to "from-env"
    When I run kproj with no config flags
    Then the resolved "<config_field>" is "from-env"

    Examples: datasheet-related flags
      | yaml_key          | env_var                 | config_field      |
      | inventory         | KPROJ_INVENTORY         | inventory         |
      | datasheet_library | KPROJ_DATASHEET_LIBRARY | datasheet_library |
      | datasheet_repo    | KPROJ_DATASHEET_REPO    | datasheet_repo    |

  Scenario Outline: ~/.kproj.yaml applies when no CLI flag or environment variable is set
    Given a ~/.kproj.yaml with "<yaml_key>" set to "from-yaml"
    When I run kproj with no config flags
    Then the resolved "<config_field>" is "from-yaml"

    Examples: datasheet-related flags
      | yaml_key          | config_field      |
      | inventory         | inventory         |
      | datasheet_library | datasheet_library |
      | datasheet_repo    | datasheet_repo    |
