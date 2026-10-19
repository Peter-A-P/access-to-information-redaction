"""The project's website: what the tool is, what it measured, and the live demonstration.

Served at redaction.peterparker.ca by the same process as the demonstration
(`sever.review.demo`), in the style of the other project pages on peterparker.ca. Built by
`sever site --out DIR` from committed files only:

- `web/`, the pages: `index.html` and `how.html` with `{{tokens}}`, `dashboard.html`,
  `style.css`, `app.js`, `dashboard.js`, `review.css` and the fonts. The stylesheet is the
  one projects 01, 02, 08, 12 and 04 share, copied rather than linked, with what this
  site adds at the end;
- the generated results, which the measurement commands write and nobody types:
  `results/results.json` and the Markdown tables under `results/` and `gate/`. Every
  figure on the page is read from one of them here, by its row label, so the page and the
  results cannot disagree. A figure that is missing or no longer parses fails the build;
- `sever/taxonomy/*.yaml`, through the loader, for the table of categories and provisions;
- one invented letter from the demonstration's own records, run through the tool at build
  time, so the example of what a reviewer sees is the engine's output, not a drawing of it.

Nothing inline in the site's own pages: the scripts and styles are files, so they work
under a content security policy that allows nothing inline. (The reviewer's screen keeps
its own inline script, which is why the host's policy still allows it; see docs/deploy.md.)

The repository is private until it is published. Links into it are written in the
templates as `<a data-repo href=...>`; built with `public=False` they become plain text, so
the public site never links to a page a stranger cannot open.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sever.review.session import Item

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
REPOSITORY = "https://github.com/Peter-A-P/access-to-information-redaction"
# The project's card on peterparker.ca. Its own page there is built from the README, which
# the portfolio reads only once the repository is public; until then the card is the page.
PROJECT_PAGE = "https://peterparker.ca/#access-to-information-redaction"
TITLE = "Hundreds of Pages, Redacted in an Afternoon"

# The templates, filled with tokens, and the files copied as they are.
PAGES = ("index.html", "how.html", "dashboard.html")
ASSETS = ("style.css", "app.js", "dashboard.js", "review.css")

# The site's menu, the same on every page of the host: the two pages of the website, the
# reviewer's screen and the dashboard. The reviewer's screen draws it too (base.html).
MENU: tuple[tuple[str, str], ...] = (
    ("/", "Overview"),
    ("/review", "Review a record yourself"),
    ("/dashboard", "Every decision, live"),
    ("/how", "How it's built"),
)


class SiteError(Exception):
    """A figure the page needs is missing from the results, or no longer reads as it did."""


def e(v: object) -> str:
    return html.escape(str(v))


def menu(current: str) -> str:
    """The menu as HTML, with the page the reader is on marked."""
    links = "\n".join(
        f'    <a href="{href}"{' aria-current="page"' if href == current else ""}>{e(label)}</a>'
        for href, label in MENU
    )
    return (
        f'<nav class="tabs" aria-label="This site">\n  <div class="tabs-inner">\n{links}\n'
        "  </div>\n</nav>"
    )


def masthead(current: str) -> str:
    """The way back to peterparker.ca, and the menu."""
    return (
        '<header class="top">\n  <div class="top-inner">\n'
        '    <a class="brand" href="https://peterparker.ca"><span class="mono-mark" '
        'aria-hidden="true">P</span>Peter Parker</a>\n'
        f'    <p class="top-nav"><a href="{PROJECT_PAGE}">Project 07: {e(TITLE)}</a></p>\n'
        "  </div>\n</header>\n" + menu(current)
    )


# -- reading the results ----------------------------------------------------------------------

# "22.4% (20.9% to 23.9%), n=3780", as the scoring code writes every rate.
_RATE = re.compile(r"(-?[\d.]+)% \((-?[\d.]+)% to (-?[\d.]+)%\), n=(\d+)")


@dataclass(frozen=True, slots=True)
class Rate:
    value: float
    low: float
    high: float
    n: int

    @property
    def pct(self) -> str:
        return f"{self.value:.1f}%"

    @property
    def ci(self) -> str:
        return f"{self.low:.1f} to {self.high:.1f}%"

    def as_json(self) -> list[float]:
        return [self.value, self.low, self.high, self.n]


def rate(text: str, what: str) -> Rate:
    m = _RATE.search(text)
    if m is None:
        raise SiteError(f"{what}: {text!r} is not a rate with an interval")
    return Rate(float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4)))


def find(text: str, pattern: str, what: str) -> re.Match[str]:
    m = re.search(pattern, text, re.S)
    if m is None:
        raise SiteError(f"{what}: the text does not match {pattern!r}")
    return m


def table_rows(markdown: str) -> list[list[str]]:
    """Every row of every table in a generated Markdown file, as stripped cells."""
    return [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in markdown.splitlines()
        if line.startswith("|") and not re.fullmatch(r"\|[-:| ]+\|", line.strip())
    ]


def row(rows: Sequence[Sequence[str]], label: str, what: str) -> Sequence[str]:
    """The first row whose first cell starts with `label`."""
    for r in rows:
        if r and r[0].startswith(label):
            return r
    raise SiteError(f"{what}: no row starting {label!r}")


def thousands(n: int) -> str:
    return f"{n:,}"


def _read(root: Path, name: str) -> str:
    path = root / name
    if not path.exists():
        raise SiteError(f"{name} is missing; run the command that writes it")
    return path.read_text(encoding="utf-8")


# -- the figures ---------------------------------------------------------------------------

SYSTEMS = {
    "full": "sever, rules then the model on the residual",
    "model_only": "model-only, no rules",
    "rules": "sever, rules only",
    "blunt": "blunt redact-all-PII",
    "sentence": "sentence-only, no document context",
}


def corpus_figures(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """The headline tables: five configurations over the labelled corpus."""
    results = json.loads(_read(root, "results/results.json"))
    by_name = {s["name"]: s for s in results["systems"]}
    f: dict[str, str] = {}
    chart: dict[str, Any] = {"systems": []}
    for key, name in SYSTEMS.items():
        s = by_name.get(name)
        if s is None:
            raise SiteError(f"results.json has no system {name!r}")
        leak = rate(s["leak_rate"], f"{name} leak")
        over = rate(s["over_redaction_rate"], f"{name} over-redaction")
        esc = rate(s["escalation_rate"], f"{name} escalation")
        for metric, r in (("leak", leak), ("over", over), ("esc", esc)):
            f[f"{key}_{metric}"] = r.pct
            f[f"{key}_{metric}_ci"] = r.ci
        f[f"{key}_leaks"] = str(s["decomposition_leaks"])
        chart["systems"].append(
            {
                "key": key,
                "name": name,
                "leak": leak.as_json(),
                "over": over.as_json(),
                "esc": esc.as_json(),
                "decomposition": {
                    "never_found": s["decomposition_detector_missed"],
                    "mislabelled": s["decomposition_detector_mislabelled"],
                    "box_short": s["decomposition_box_too_short"],
                    "decision": s["decomposition_decision_wrong"],
                },
            }
        )
        if key == "rules":
            chart["per_code"] = {
                code: rate(v, f"over-redaction {code}").as_json()
                for code, v in s["per_code_over_redaction"].items()
            }
            chart["per_code_leak"] = {
                code: rate(v, f"leak {code}").as_json() for code, v in s["per_code_leak"].items()
            }
            f["recall"] = rate(s["detector_recall"], "recall").pct
            f["rules_mislabelled"] = str(s["decomposition_detector_mislabelled"])
            f["rules_never_found"] = str(s["decomposition_detector_missed"])
            f["rules_decision_wrong"] = str(s["decomposition_decision_wrong"])
            f["rules_box_short"] = str(s["decomposition_box_too_short"])
            f["k2_over"] = rate(s["per_code_over_redaction"]["K2"], "K2").pct
            f["k1_over"] = rate(s["per_code_over_redaction"]["K1"], "K1").pct
    corpus = results["corpus"]
    labels = sum(int(v) for v in corpus["labels_by_code"].values())
    f["corpus_pages"] = str(corpus["pages"])
    f["corpus_documents"] = str(corpus["documents"])
    f["corpus_spans"] = thousands(labels)
    f["must_release"] = thousands(rate(by_name[SYSTEMS["rules"]]["over_redaction_rate"], "n").n)
    f["must_withhold"] = thousands(rate(by_name[SYSTEMS["rules"]]["leak_rate"], "n").n)
    f["results_date"] = results["generated_on"]
    pdf = results["pdf_leak_test"]
    if not pdf["ocr_channel_ran"]:
        raise SiteError("the PDF leak test's OCR channel did not run; the page claims it did")
    f["pdf_boxes"] = thousands(int(pdf["boxes_tested"]))
    f["pdf_recoverable"] = str(pdf["recoverable"])
    f["pdf_documents"] = str(pdf["documents"])
    cost = results["cost"]
    f["model_cost_page"] = f"US${cost['usd_per_page']:.4f}"
    f["model_cost_page_cad"] = f"CA${cost['usd_per_page'] * 1.35:.4f}"
    f["model_name"] = results["model"].split("/")[-1]
    f["model_asks"] = thousands(int(results["model_asks"]))
    # The model's trade in counts: what it released correctly and what it leaked.
    rules, full = by_name[SYSTEMS["rules"]], by_name[SYSTEMS["full"]]
    f["model_extra_leaks"] = str(
        full["decomposition_decision_wrong"] - rules["decomposition_decision_wrong"]
    )
    return f, chart


def reviewer_figures(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """The reviewer time study."""
    text = _read(root, "results/reviewer.md")
    rows = table_rows(text)
    f: dict[str, str] = {}
    with_p = row(rows, "proposals", "reviewer arms")
    unaided = row(rows, "unaided", "reviewer arms")
    for key, r in (("with", with_p), ("unaided", unaided)):
        m = find(r[1], r"(\d+)s per page \((\d+) to (\d+)\)", f"seconds, {key}")
        f[f"secs_{key}"] = m.group(1)
        f[f"secs_{key}_ci"] = f"{m.group(2)} to {m.group(3)} s"
    m = find(
        text,
        r"unaided review took \*\*([\d.]+) times\*\* as long as review with proposals "
        r"\(([\d.]+) to ([\d.]+)",
        "paired speed-up",
    )
    f["speedup"], f["speedup_ci"] = m.group(1), f"{m.group(2)} to {m.group(3)}"
    f["study_records"] = find(text, r"On the (\d+) records reviewed in both arms", "records").group(1)
    leak_with = rate(row(rows, "reviewer, with proposals", "leaks")[1], "leak with")
    leak_un = rate(row(rows, "reviewer, unaided", "leaks")[1], "leak unaided")
    tool_alone = row(rows, "the tool's proposals, nobody reviewing", "tool alone")
    over_with = rate(row(rows, "reviewer, with proposals", "over")[3], "over with")
    over_un = rate(row(rows, "reviewer, unaided", "over")[3], "over unaided")
    f["study_leak_with"], f["study_leak_with_ci"] = leak_with.pct, leak_with.ci
    f["study_leak_unaided"], f["study_leak_unaided_ci"] = leak_un.pct, leak_un.ci
    f["study_over_with"], f["study_over_unaided"] = over_with.pct, over_un.pct
    f["study_tool_leak"] = rate(tool_alone[1], "tool alone leak").pct
    f["study_tool_over"] = rate(tool_alone[3], "tool alone over").pct
    f.update(savings(int(f["secs_unaided"]), int(f["secs_with"])))
    f["leak_ratio"] = f"{leak_un.value / leak_with.value:.1f}"
    reviewers = [r for r in rows if r and re.fullmatch(r"reviewer-\d+", r[0])]
    if len(reviewers) < 1:
        raise SiteError("results/reviewer.md has no per-reviewer rows")
    f["reviewers"] = str(len(reviewers))
    f["reviewers_word"] = _number_word(len(reviewers))
    f["reviewers_word_cap"] = f["reviewers_word"].capitalize()
    chart = {
        "reviewers": [
            {"name": r[0].replace("-", " ").capitalize(), "with": float(r[1]), "unaided": float(r[2])}
            for r in reviewers
        ],
        "leak": {"with": leak_with.as_json(), "unaided": leak_un.as_json()},
    }
    return f, chart


# What the measured saving would add up to, at a volume someone else published. Not a
# measurement: the seconds are the study's, on one-page invented records, and the volume is
# the federal government's, on real ones. The page says both.
FEDERAL_PAGES = 10_326_722
FEDERAL_PAGES_YEAR = "2023-24"
FEDERAL_PAGES_SOURCE = (
    "https://www.canada.ca/en/treasury-board-secretariat/services/access-information-privacy/"
    "statistics-atip/information-privacy-statistical-report-2023-2024.html"
)
# "Pages processed increased by 25% from the previous year, to 10,326,722." IRCC excluded.
FEDERAL_PAGES_CHECKED = "2026-10-18"
# A full-time year of reviewing: 37.5 hours a week for 48 weeks.
HOURS_PER_YEAR = 1_800
# What a year of that costs: the top step of PM-04, the level federal ATIP analysts are most
# often classified at, in the Program and Administrative Services agreement, effective
# 2024-06-21 with the wage adjustment. Salary alone, before benefits or overhead, so the
# dollar figure is the low end.
ANALYST_SALARY = 87_108
ANALYST_SALARY_SOURCE = (
    "https://www.canada.ca/en/treasury-board-secretariat/topics/pay/collective-agreements/pa.html"
)


def savings(secs_unaided: int, secs_with: int) -> dict[str, str]:
    saved = secs_unaided - secs_with
    hours = FEDERAL_PAGES * saved / 3600
    return {
        "secs_saved": str(saved),
        "hours_saved": f"{round(hours, -3):,.0f}",
        "people_saved": f"{round(hours / HOURS_PER_YEAR):,}",
        "federal_pages": f"{FEDERAL_PAGES:,}",
        "federal_pages_year": FEDERAL_PAGES_YEAR,
        "federal_pages_source": FEDERAL_PAGES_SOURCE,
        "hours_per_year": f"{HOURS_PER_YEAR:,}",
        "dollars_saved": f"{hours / HOURS_PER_YEAR * ANALYST_SALARY / 1e6:.1f}",
        "analyst_salary": f"{ANALYST_SALARY:,}",
        "analyst_salary_source": ANALYST_SALARY_SOURCE,
    }


def _number_word(n: int) -> str:
    words = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    return words[n] if n < len(words) else str(n)


RELEASE_SETS = (
    ("releases", "Defence, 2001 to 2010", "learned from"),
    ("releases-heldout", "External Affairs, Immigration", "held out"),
    ("releases-fresh", "Immigration, Health, Justice", "held out, registered first"),
)


def release_figures(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """The published federal releases: what the tool would withhold of what a person released."""
    f: dict[str, str] = {}
    sets: list[dict[str, Any]] = []
    for key, label, kind in RELEASE_SETS:
        text = _read(root, f"results/{key}.md")
        rows = table_rows(text)
        corpus = find(
            text, r"\*\*Corpus:\*\* (\d+) published release packages, (\d+) pages", f"{key} corpus"
        )
        first = rate(row(rows, "as scored until", key)[1], f"{key} before")
        shipped = next(
            (r for r in rows if r and ("as it now ships" in r[0])), None
        )
        if shipped is None:
            raise SiteError(f"results/{key}.md has no 'as it now ships' row")
        now = rate(shipped[1], f"{key} now")
        slug = key.replace("releases-", "").replace("releases", "defence")
        f[f"rel_{slug}_packages"] = corpus.group(1)
        f[f"rel_{slug}_pages"] = corpus.group(2)
        f[f"rel_{slug}_before"] = first.pct
        f[f"rel_{slug}_now"], f[f"rel_{slug}_now_ci"] = now.pct, now.ci
        f[f"rel_{slug}_spans"] = thousands(now.n)
        sets.append(
            {
                "key": slug,
                "label": label,
                "kind": kind,
                "packages": int(corpus.group(1)),
                "pages": int(corpus.group(2)),
                "before": first.as_json(),
                "now": now.as_json(),
            }
        )
    f["rel_pages_total"] = str(sum(s["pages"] for s in sets))
    f["rel_packages_total"] = str(sum(s["packages"] for s in sets))
    return f, {"releases": sets}


def scan_figures(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    text = _read(root, "results/scanned.md")
    rows = table_rows(text)
    f: dict[str, str] = {}
    profiles = []
    for name in ("native", "clean", "scanner", "photocopy", "fax"):
        r = row(rows, name, f"scan {name}")
        leak, over = rate(r[5], f"{name} leak"), rate(r[6], f"{name} over")
        profiles.append({"name": name, "cer": r[1], "leak": leak.as_json(), "over": over.as_json()})
        f[f"scan_{name}_leak"], f[f"scan_{name}_over"], f[f"scan_{name}_cer"] = (
            leak.pct,
            over.pct,
            r[1],
        )
    flat = [r for r in rows if r and r[0] == "scanner" and len(r) == 5]
    if not flat:
        raise SiteError("results/scanned.md has no layout table row for the scanner")
    f["scan_scanner_flat_over"] = rate(flat[0][3], "scanner flat").pct
    f["scan_documents"] = find(text, r"\*\*Corpus:\*\* (\d+) documents", "scan corpus").group(1)
    layout = table_rows(_read(root, "results/layout.md"))
    f["layout_flat_over"] = rate(row(layout, "flattened", "layout")[2], "flat").pct
    f["layout_recovered_over"] = rate(row(layout, "recovered", "layout")[2], "recovered").pct
    return f, {"scans": profiles}


def gate_figures(root: Path) -> dict[str, str]:
    text = _read(root, "gate/decision.md")
    f = {"gate_verdict": find(text, r"## Gate: (\w+)", "gate verdict").group(1)}
    rows = table_rows(text)
    no_leak = row(rows, "no_leak", "gate no_leak")
    f["gate_items"] = no_leak[1]
    f["gate_rules"] = find(no_leak[2], r"^([\d.]+%)", "gate baseline").group(1)
    f["gate_model"] = find(no_leak[3], r"^([\d.]+%)", "gate candidate").group(1)
    m = find(text, r"(\d+) worse and (\d+) better", "gate counts")
    f["gate_worse"], f["gate_better"] = m.group(1), m.group(2)
    return f


def directory_figures(root: Path) -> dict[str, str]:
    rows = table_rows(_read(root, "results/directory.md"))
    none = row(rows, "no directory", "directory none")
    names = row(rows, "100% of employees, matched on email and name", "directory names")
    email = next((r for r in rows if r and r[0] == "100% of employees, matched on email"), None)
    if email is None:
        raise SiteError("results/directory.md has no email-only row")
    base_leak, name_leak = rate(none[1], "leak"), rate(names[1], "names leak")
    return {
        "dir_leak_none": base_leak.pct,
        "dir_leak_names": name_leak.pct,
        "dir_leak_factor_word": _number_word(round(name_leak.value / base_leak.value)),
        "dir_k2_none": rate(none[3], "k2 none").pct,
        "dir_k2_email": rate(email[3], "k2 email").pct,
        "dir_leak_email": rate(email[1], "email leak").pct,
        "dir_listed_leaks": names[6],
    }


# -- the law, as data ----------------------------------------------------------------------

_DECISION_WORDS = {
    "redact": ("Withhold", "withhold"),
    "keep": ("Release", "release"),
    "escalate": ("Withhold and escalate", "escalate"),
    "flag": ("Flag for the reviewer", "flag"),
}


# How the table names each statute. A statute the table does not know fails the build.
STATUTE_SHORT = {
    "atia": "ATIA",
    "privacy": "Privacy Act",
    "privacy_regs": "Privacy Regs",
    "atippa": "ATIPPA",
}


def taxonomy_table() -> tuple[str, dict[str, str]]:
    """The categories, what each does federally and in Newfoundland and Labrador, and the
    provisions each rests on, as table rows."""
    from sever.taxonomy.loader import default_taxonomy

    t = default_taxonomy()
    out = []
    for c in t.categories:
        cells = [
            f'<th scope="row" class="wrap"><span class="code-chip {_DECISION_WORDS[c.decision.value][1]}">'
            f"{e(c.code)}</span> {e(c.name)}</th>"
        ]
        for j in ("federal", "nl"):
            word, cls = _DECISION_WORDS[t.decision(c.code, j).value]
            cites = ", ".join(
                f"{STATUTE_SHORT[p.statute]} {p.section}" for p in t.provisions(c.code, j)
            ) or "no provision cited: a person decides"
            cells.append(
                f'<td class="wrap"><span class="does {cls}">{e(word)}</span>'
                f'<span class="cites">{e(cites)}</span></td>'
            )
        out.append("<tr>" + "".join(cells) + "</tr>")
    summary = t.verification_summary()
    verified = sum(v for v, _ in summary.values())
    total = sum(n for _, n in summary.values())
    if verified != total:
        raise SiteError(f"{total - verified} provisions are not verified; the page says all are")
    return "\n".join(out), {
        "provisions": str(total),
        "provisions_federal": str(summary["federal"][1]),
        "provisions_nl": str(summary["nl"][1]),
        "categories": str(len(list(t.categories))),
    }


# -- the rules, in order --------------------------------------------------------------------

# What each rule does, in words, by the function's name. The build fails when the code's order
# has a rule this list does not describe, so the page cannot fall out of step with the rules.
RULE_WORDS: dict[str, tuple[str, str, str]] = {
    "requester_ambiguous": (
        "E1", "Could it be the requester, or someone else?",
        "A first name the requester shares with another person in the record is escalated, "
        "not guessed.",
    ),
    "requester_own_information": (
        "K1", "The requester's own information",
        "Their name, address, file number and contact details go back to them.",
    ),
    "archival_age": (
        "K7", "Born more than 110 years ago, in an archival record",
        "Only when the request is for archival records, and only on a birth the record "
        "itself shows.",
    ),
    "inherently_sensitive": (
        "R1", "Sensitive whoever holds it",
        "A health card or social insurance number, a date of birth or a bank account is "
        "withheld: a director's health number is not about being a director.",
    ),
    "family_relationship": (
        "R1", "A family word that points at someone",
        '"The client\'s sibling" identifies the sibling to a requester who knows the family, '
        "so it goes with the name.",
    ),
    "complaint_party": (
        "R1", "The parties to a confidential complaint",
        "Withheld with their job titles: a title released beside a severed name identifies "
        "the one person who holds it.",
    ),
    "not_personal_information": (
        "K6", "Not about a person at all",
        "Places, dates, organisations, programmes and statutes.",
    ),
    "mixed_span": (
        "E2", "Two people in one span",
        "Where the cut between them cannot be made cleanly, the reviewer is asked where.",
    ),
    "official_capacity": (
        "K2", "An official acting in that capacity",
        "A name paired with a title anywhere in the record: in a signature block, a "
        "letterhead or an email header.",
    ),
    "official_capacity_contact": (
        "K2", "An official's work contact details",
        "A work telephone number or address in the official's own signature block.",
    ),
    "public_register": (
        "K3", "Already public",
        "On a published register, such as the list of ministers, with the source recorded.",
    ),
    "staff_directory": (
        "K2", "On the staff directory",
        "Matched on the work email address alone, and only when the public body supplies "
        "a directory.",
    ),
    "military_rank": (
        "K2", "A rank is a title",
        "In a Defence record, a rank beside a name places the person as a member acting in "
        "that capacity.",
    ),
    "deceased_over_twenty_years": (
        "K4", "Dead more than twenty years",
        "Only when the record itself states the date of death; otherwise the person may be "
        "alive.",
    ),
}


def rule_steps() -> str:
    from sever.decide.rules import DEFAULT_RULES
    from sever.taxonomy.loader import default_taxonomy

    taxonomy = default_taxonomy()
    out = []
    for rule in DEFAULT_RULES:
        name = getattr(rule, "__name__", str(rule))
        if name not in RULE_WORDS:
            raise SiteError(f"the rule {name!r} has no description on the site")
        code, title, body = RULE_WORDS[name]
        kind = _DECISION_WORDS[taxonomy.decision(code).value][1]
        out.append(
            f'      <li><span class="code-chip {kind}">{code}</span><strong>{e(title)}</strong>'
            f"<span>{e(body)}</span></li>"
        )
    out.append(
        '      <li class="optional"><span class="code-chip optional">?</span><strong>The model, '
        "if it is switched on</strong><span>Asked about what no rule settled, on placeholders, "
        "through the gateway; its answer is used only above the measured threshold.</span></li>"
    )
    out.append(
        '      <li><span class="code-chip escalate">E1</span><strong>Nothing settled it'
        "</strong><span>Withhold, and ask a person.</span></li>"
    )
    return "\n".join(out)


# -- the example ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Example:
    html: str
    requester: str
    counts: Mapping[str, int]
    reasons: str


def _kind(p: Any) -> str:
    if p.code == "K6":
        return "none"
    if p.is_escalation:
        return "escalate"
    return "withhold" if p.withholds else "release"


def example(items: Iterable[Item]) -> Example:
    """One of the demonstration's records, as the tool proposes it: every span marked by what the
    tool would do with it, with the category and the reason on the mark."""
    from sever.ingest.document import DocumentType
    from sever.taxonomy.loader import default_taxonomy

    taxonomy = default_taxonomy()
    # The memorandum, because it is the record where context decides most visibly: the same
    # job title withheld for one person and released for another, and the requester named in
    # a file about someone else. The letter if a smaller set of records has no memorandum.
    item = next(
        (
            i
            for kind in (DocumentType.HR_MEMORANDUM, DocumentType.CORRESPONDENCE)
            for i in items
            if i.document.doc_type is kind
        ),
        None,
    )
    if item is None:
        raise SiteError("the demonstration has no record to show")
    page = item.document.page(1)
    parts: list[str] = []
    cursor = 0
    counts = {"withhold": 0, "release": 0, "escalate": 0, "none": 0}
    picked: dict[str, tuple[str, str, str]] = {}
    for p in sorted(item.on_page(1), key=lambda p: p.detection.offsets.start):
        o = p.detection.offsets
        if o.start < cursor:
            continue
        kind = _kind(p)
        counts[kind] += 1
        name = taxonomy[p.code].name
        note = f"{p.code}, {name}. {p.reason}"
        parts.append(e(page.text[cursor : o.start]))
        parts.append(
            f'<mark class="x-{kind}" tabindex="0" data-code="{e(p.code)}" '
            f'data-note="{e(note)}" title="{e(note)}">{e(page.text[o.start : o.end])}</mark>'
        )
        cursor = o.end
        if kind != "none" and p.code not in picked:
            picked[p.code] = (page.text[o.start : o.end], name, p.reason)
    parts.append(e(page.text[cursor:]))
    reasons = "\n".join(
        f'<li><span class="code-chip {_kind_for_code(taxonomy, code)}">{e(code)}</span> '
        f"<strong>{e(text)}</strong>: {e(name)}. <span class=\"why\">{e(reason)}</span></li>"
        for code, (text, name, reason) in sorted(picked.items(), key=lambda kv: _order(kv[0]))
    )
    return Example(
        html="".join(parts), requester=item.requester or "", counts=counts, reasons=reasons
    )


def _kind_for_code(taxonomy: Any, code: str) -> str:
    return _DECISION_WORDS[taxonomy.decision(code).value][1]


def _order(code: str) -> tuple[int, str]:
    return ("KRE".index(code[0]) if code[0] in "KRE" else 9, code)


# -- engineering ---------------------------------------------------------------------------


def engineering(root: Path) -> dict[str, str]:
    tests = sum(
        len(re.findall(r"^(?:async )?def test_", p.read_text(encoding="utf-8"), re.M))
        for p in (root / "tests").glob("test_*.py")
    )
    code = sum(
        len(p.read_text(encoding="utf-8").splitlines()) for p in (root / "sever").rglob("*.py")
    )
    return {"tests": thousands(tests), "code_lines": thousands(code)}


# -- building ------------------------------------------------------------------------------

_TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
_REPO_LINK = re.compile(r'<a data-repo href="[^"]*">(.*?)</a>', re.S)


def fill(template: str, values: Mapping[str, str], *, page: str) -> str:
    missing = sorted({m.group(1) for m in _TOKEN.finditer(template)} - set(values))
    if missing:
        raise SiteError(f"{page}: no value for {', '.join(missing)}")
    return _TOKEN.sub(lambda m: values[m.group(1)], template)


def repository_links(text: str, *, public: bool) -> str:
    if public:
        return text.replace("<a data-repo ", "<a ")
    return _REPO_LINK.sub(lambda m: f'<span class="repo-ref">{m.group(1)}</span>', text)


@dataclass(frozen=True, slots=True)
class Built:
    out: Path
    pages: tuple[str, ...]
    figures: int


def build(
    out: Path,
    *,
    items: Sequence[Item] | None = None,
    root: Path = ROOT,
    public: bool = False,
    today: dt.date | None = None,
) -> Built:
    """Write the site to `out`. `items` are the demonstration's records; built from the
    seed when not given, which runs the detector."""
    if items is None:
        from sever.review.demo import demo_items

        items = demo_items()
    values: dict[str, str] = {}
    data: dict[str, Any] = {}
    for f, d in (
        corpus_figures(root),
        reviewer_figures(root),
        release_figures(root),
        scan_figures(root),
    ):
        values.update(f)
        data.update(d)
    values.update(gate_figures(root))
    values.update(directory_figures(root))
    values.update(engineering(root))
    rows, law = taxonomy_table()
    values.update(law)
    values["taxonomy_rows"] = rows
    values["rule_steps"] = rule_steps()
    from sever.taxonomy.loader import default_taxonomy

    data["code_names"] = {c.code: c.name for c in default_taxonomy().categories}
    ex = example(items)
    values["example_letter"] = ex.html
    values["example_requester"] = e(ex.requester)
    values["example_reasons"] = ex.reasons
    values["example_legend"] = "\n".join(
        f'          <li><span class="key-chip {kind}"></span><span><strong>{ex.counts[kind]}</strong> '
        f"{e(words)}</span></li>"
        for kind, words in (
            ("withhold", "to withhold: a third party"),
            ("escalate", "to withhold and escalate: the record does not say who they are"),
            ("release", "to release: the requester, officials, the public"),
            ("none", "not personal at all: places, dates, organisations"),
        )
        if ex.counts[kind]
    )
    values["demo_records"] = str(len(items))
    values["demo_records_word"] = _number_word(len(items))
    values["repository"] = REPOSITORY
    values["project_page"] = PROJECT_PAGE
    values["built"] = (today or dt.date.today()).isoformat()
    values["repository_line"] = (
        f'<a href="{REPOSITORY}">github.com/Peter-A-P/access-to-information-redaction</a>'
        if public
        else "the project's repository, which is published with the first release"
    )
    for current, name in (("/", "index.html"), ("/how", "how.html"), ("/dashboard", "dashboard.html")):
        values[f"masthead_{name.split('.')[0]}"] = masthead(current)

    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    for name in PAGES:
        text = fill((WEB / name).read_text(encoding="utf-8"), values, page=name)
        (out / name).write_text(repository_links(text, public=public), encoding="utf-8")
    for name in ASSETS:
        shutil.copy2(WEB / name, out / name)
    shutil.copytree(WEB / "fonts", out / "fonts")
    (out / "data" / "site.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    return Built(out=out, pages=PAGES, figures=len(values))


__all__ = [
    "ASSETS",
    "MENU",
    "PAGES",
    "PROJECT_PAGE",
    "REPOSITORY",
    "TITLE",
    "Built",
    "Rate",
    "SiteError",
    "build",
    "corpus_figures",
    "example",
    "fill",
    "masthead",
    "menu",
    "rate",
    "release_figures",
    "repository_links",
    "reviewer_figures",
    "scan_figures",
    "taxonomy_table",
]
