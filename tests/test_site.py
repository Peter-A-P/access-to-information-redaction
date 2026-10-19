"""The project's website: every figure read from a results file, and nothing typed.

The site is the first thing a stranger reads, so it is held to what the README is held to:
no number that a measurement command did not write, no page that silently drops a figure
it could not read, and no link into the repository while the repository is private.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sever import site
from sever.decide.rules import DEFAULT_RULES
from sever.review.demo import demo_items
from sever.review.session import Item

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def items() -> tuple[Item, ...]:
    return demo_items(documents=4)


@pytest.fixture(scope="module")
def built(items: tuple[Item, ...], tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("site")
    site.build(out, items=items)
    return out


def page(built: Path, name: str) -> str:
    return (built / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", site.PAGES)
def test_every_token_is_filled(built: Path, name: str) -> None:
    assert "{{" not in page(built, name)


@pytest.mark.parametrize("name", site.PAGES)
def test_no_script_or_style_is_inline(built: Path, name: str) -> None:
    """The site's own pages work under a policy that allows nothing inline."""
    text = page(built, name)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text)
    assert "<style" not in text and " style=" not in text
    assert not re.search(r"\son[a-z]+=", text)


def test_the_headline_figures_are_the_results_files_own(built: Path) -> None:
    results = json.loads((ROOT / "results/results.json").read_text(encoding="utf-8"))
    rules = next(s for s in results["systems"] if s["name"] == "sever, rules only")
    blunt = next(s for s in results["systems"] if s["name"] == "blunt redact-all-PII")
    text = page(built, "index.html")
    for cell in (rules["over_redaction_rate"], rules["leak_rate"], blunt["over_redaction_rate"]):
        assert site.rate(cell, "test").pct in text
    reviewer = (ROOT / "results/reviewer.md").read_text(encoding="utf-8")
    speedup = re.search(r"took \*\*([\d.]+) times\*\*", reviewer)
    assert speedup is not None and f"{speedup.group(1)}&times;" in text


def test_a_figure_that_cannot_be_read_fails_the_build(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "reviewer.md").write_text("| proposals | nothing here |\n", encoding="utf-8")
    with pytest.raises(site.SiteError):
        site.reviewer_figures(tmp_path)


def test_a_token_without_a_value_fails_the_build() -> None:
    with pytest.raises(site.SiteError, match="no value for missing"):
        site.fill("{{present}} and {{missing}}", {"present": "x"}, page="t")


def test_a_private_repository_is_never_linked(built: Path) -> None:
    for name in site.PAGES:
        assert "github.com" not in page(built, name)
    assert "repo-ref" in page(built, "index.html")


def test_a_public_repository_is_linked() -> None:
    text = '<a data-repo href="https://github.com/x/y/blob/main/a.md">a.md</a>'
    assert site.repository_links(text, public=True) == '<a href="https://github.com/x/y/blob/main/a.md">a.md</a>'
    assert site.repository_links(text, public=False) == '<span class="repo-ref">a.md</span>'


def test_the_rules_page_follows_the_code(built: Path) -> None:
    """The rules are listed in the order the code applies them, and the list cannot fall out
    of step: a rule the site does not describe fails the build."""
    text = page(built, "how.html")
    titles = [site.RULE_WORDS[r.__name__][1] for r in DEFAULT_RULES]
    positions = [text.index(site.e(t)) for t in titles]
    assert positions == sorted(positions)


def test_a_rule_the_site_does_not_describe_fails_the_build(monkeypatch: pytest.MonkeyPatch) -> None:
    words = dict(site.RULE_WORDS)
    del words["official_capacity"]
    monkeypatch.setattr(site, "RULE_WORDS", words)
    with pytest.raises(site.SiteError, match="official_capacity"):
        site.rule_steps()


def test_the_example_is_the_engines_own_output(built: Path, items: tuple[Item, ...]) -> None:
    letter = next(i for i in items if i.document.doc_type.value == "hr_memorandum")
    text = page(built, "index.html")
    marks = re.findall(r'<mark class="x-[a-z]+"[^>]*>', text)
    proposed = {(p.detection.offsets.start, p.detection.offsets.end) for p in letter.on_page(1)}
    assert 0 < len(marks) <= len(proposed)
    assert site.e(letter.requester or "") in text


def test_every_provision_is_in_the_law_table(built: Path) -> None:
    from sever.taxonomy.loader import default_taxonomy

    taxonomy = default_taxonomy()
    text = page(built, "index.html")
    for c in taxonomy.categories:
        for j in ("federal", "nl"):
            for p in taxonomy.provisions(c.code, j):
                assert f"{site.STATUTE_SHORT[p.statute]} {p.section}" in text


def test_the_hours_are_the_measured_saving_times_the_published_volume() -> None:
    s = site.savings(130, 56)
    assert s["secs_saved"] == "74"
    # 10,326,722 pages at 74 seconds is 212,271 hours, quoted to the thousand.
    assert s["hours_saved"] == "212,000"
    assert s["people_saved"] == "118"
    # 117.9 full-time years at $87,108.
    assert s["dollars_saved"] == "10.3"


def test_the_estimate_is_called_an_estimate(built: Path) -> None:
    text = page(built, "index.html")
    assert text.count("an estimate:") == 2
    assert site.FEDERAL_PAGES_SOURCE in text and site.ANALYST_SALARY_SOURCE in text


def test_what_the_page_says_about_the_memorandum_is_what_the_engine_did(built: Path) -> None:
    """The verdict under the example names spans and what happened to them; if the engine
    changes its mind, this fails before the page says something untrue."""
    text = page(built, "index.html")

    def kinds(span: str) -> set[str]:
        found = set(re.findall(r'<mark class="x-([a-z]+)"[^>]*>' + re.escape(span) + "</mark>", text))
        assert found, span
        return found

    assert kinds("Regional Director") == {"withhold"}
    # The recipient's title on the To: line, and the complainant's in the body.
    assert kinds("Director of Operations") == {"none", "withhold"}
    assert kinds("Bernadette Halleran") == {"release"}
    assert kinds("Desmond Okonkwo") == {"escalate"}


@pytest.mark.parametrize("name", site.PAGES)
def test_the_sites_own_files_carry_their_fingerprint(built: Path, name: str) -> None:
    """A changed stylesheet must not wait out a browser's cache."""
    text = page(built, name)
    assert '"/style.css"' not in text
    assert f'"/style.css?v={site.asset_version("style.css")}"' in text
