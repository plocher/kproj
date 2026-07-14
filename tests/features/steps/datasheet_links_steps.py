"""Step definitions for ``datasheet_links.feature`` (kproj#29).

Drives ``PublishWorkflow``'s injected ``datasheet_name_lookup`` seam
(see ``publish_steps.py``'s ``_default_fake_datasheet_lookup``) so no
scenario here ever execs a real ``jbom`` subprocess.
"""

from __future__ import annotations

from typing import Any

from behave import given, then  # type: ignore[import-untyped]

from kproj.config import GENERIC_SITE_PROFILE
from kproj.model.finding import Finding
from kproj.model.severity import Severity

# ─────────────────────────── Given steps ──────────────────────────────────────


@given('jbom reports the datasheet name "{name}" for this project')
def step_jbom_reports_one_datasheet_name(context: Any, name: str) -> None:
    """Have the faked datasheet-name lookup return one curated name."""
    context.datasheet_names = (name,)


@given("jbom reports no datasheet names for this project")
def step_jbom_reports_no_datasheet_names(context: Any) -> None:
    """Have the faked datasheet-name lookup return no curated names."""
    context.datasheet_names = ()


@given('the datasheet repo is configured as "{owner_repo}"')
def step_datasheet_repo_configured(context: Any, owner_repo: str) -> None:
    """Override ``KprojConfig.datasheet_repo`` for this scenario (kproj#37)."""
    context.datasheet_repo = owner_repo


@given("jbom is too old to recognize the Datasheet Name field")
def step_jbom_too_old(context: Any) -> None:
    """Simulate a `jbom bom` invocation whose output has no Datasheet Name column.

    Mirrors the real degrade-gracefully path in
    :func:`kproj.common.datasheet_library.read_datasheet_names`: no names,
    one advisory ``datasheet_field_missing`` warning Finding.
    """
    context.datasheet_names = ()
    context.datasheet_lookup_findings = (
        Finding(
            severity=Severity.WARNING,
            field="datasheet_field_missing",
            value="jbom bom <project> -f 'Datasheet Name' -o -",
            reason="this jBOM version predates the Datasheet Name field",
        ),
    )


# ─────────────────────────── Then steps ───────────────────────────────────────


def _project_index_text(context: Any) -> str:
    P = getattr(context, "project_name", "MyProject")
    index_file = GENERIC_SITE_PROFILE.project_index_path(context.site_repo, P)
    assert index_file.exists(), f"{index_file} not found in {context.site_repo}"
    return index_file.read_text(encoding="utf-8")


@then('the project page links the datasheet "{name}" for view and download')
def step_project_page_links_datasheet(context: Any, name: str) -> None:
    """Assert the project index front-matter carries the name + view + download URLs."""
    content = _project_index_text(context)
    assert f"name: {name}" in content, f"datasheet {name!r} not found in:\n{content}"
    assert f"datasheets/{name}.pdf" in content, (
        f"expected a datasheets/{name}.pdf URL in:\n{content}"
    )
    assert "view:" in content and "download:" in content, (
        f"expected view: + download: URLs in:\n{content}"
    )


@then('the project page links the datasheet "{name}" to repo "{owner_repo}"')
def step_project_page_links_datasheet_to_repo(context: Any, name: str, owner_repo: str) -> None:
    """Assert the deep-link URLs point at the configured owner/repo slug."""
    content = _project_index_text(context)
    assert f"github.com/{owner_repo}/blob/main/datasheets/{name}.pdf" in content, (
        f"expected a github.com/{owner_repo}/... view URL in:\n{content}"
    )
    assert f"raw.githubusercontent.com/{owner_repo}/main/datasheets/{name}.pdf" in content, (
        f"expected a raw.githubusercontent.com/{owner_repo}/... download URL in:\n{content}"
    )


@then("the project page has no datasheet links")
def step_project_page_has_no_datasheets(context: Any) -> None:
    """Assert the project index front-matter has no ``datasheets:`` key."""
    content = _project_index_text(context)
    assert "datasheets:" not in content, f"unexpected datasheets: key in:\n{content}"
