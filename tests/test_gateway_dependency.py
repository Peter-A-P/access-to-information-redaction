"""How `boundary` is depended on, which is a correctness question rather than packaging.

The name `boundary` on PyPI is an unrelated package that stops at 0.3.4, so a dependency
line naming it resolves to a stranger's code. Two things are pinned here: that no such
line comes back, and that the version floor the line used to carry is enforced where the
library is actually used. Both run without `boundary` installed, which is the point: CI
has no copy of project 04 and this is the test that would have caught the line that broke
it.
"""

from __future__ import annotations

import sys
import tomllib
import types
from pathlib import Path

import pytest

from sever.gateway import (
    MINIMUM_BOUNDARY,
    BoundaryUnavailable,
    _parsed,
    available,
    installed_version,
    require_boundary,
)

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _fake_boundary(version: str | None) -> types.ModuleType:
    module = types.ModuleType("boundary")
    if version is not None:
        module.__version__ = version  # type: ignore[attr-defined]
    return module


def test_nothing_declares_a_dependency_named_boundary() -> None:
    """The line that broke CI, and would have installed somebody else's package."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    declared = list(project.get("dependencies", ()))
    for extra in project.get("optional-dependencies", {}).values():
        declared.extend(extra)
    offending = [d for d in declared if d.split("[")[0].split(">")[0].strip() == "boundary"]
    assert offending == [], (
        f"boundary is a private repository installed by path, not a resolvable "
        f"dependency; PyPI's `boundary` is an unrelated package. Found: {offending}"
    )


def test_a_boundary_below_the_floor_raises_rather_than_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0.6.1 masks `555-0199` and sends the area code of `(709) 555-0199` in clear beside
    its own placeholder."""
    monkeypatch.setitem(sys.modules, "boundary", _fake_boundary("0.6.1"))
    with pytest.raises(BoundaryUnavailable, match=r"0\.6\.4 or newer"):
        require_boundary()
    assert available() is False


def test_the_floor_itself_is_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boundary", _fake_boundary("0.6.4"))
    assert require_boundary().__version__ == "0.6.4"
    assert available() is True


def test_a_newer_boundary_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no upper bound: a break in 04 should fail a test, not a version check."""
    monkeypatch.setitem(sys.modules, "boundary", _fake_boundary("0.12.0"))
    assert available() is True


def test_a_boundary_that_reports_no_version_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreported version is the PyPI package or a broken install, not project 04."""
    monkeypatch.setitem(sys.modules, "boundary", _fake_boundary(None))
    assert installed_version() is None
    with pytest.raises(BoundaryUnavailable):
        require_boundary()


def test_boundary_missing_says_where_it_comes_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boundary", None)
    with pytest.raises(BoundaryUnavailable, match="04-compliant-ai-gateway"):
        require_boundary()
    assert installed_version() is None


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.5.5", (0, 5, 5)),
        ("0.5.5.dev1", (0, 5, 5)),
        ("1.0.0rc1", (1, 0)),
        ("0.3.4", (0, 3, 4)),
    ],
)
def test_versions_parse_to_what_compares(version: str, expected: tuple[int, ...]) -> None:
    assert _parsed(version) == expected


def test_the_pypi_package_would_not_clear_the_floor() -> None:
    """0.3.4 is the highest the unrelated PyPI `boundary` goes, and it is below the floor."""
    assert _parsed("0.3.4") < MINIMUM_BOUNDARY
