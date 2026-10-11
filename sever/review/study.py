"""The reviewer time study, run by one command.

Section 10 asks for reviewer minutes per page with and without proposals, and it is the
one number in the definition of done that a program cannot produce. Everything a program
*can* do is here, so that the person running the study does nothing but sit people down:
`sever study` picks the records, decides which arm each one is in, serves them one after
another in the right order, times each page, and keeps every reviewer's work apart.

## The design, and why each part of it is there

**Nobody reviews the same record twice.** The obvious design, one reviewer doing the same
twenty pages with and then without proposals, measures memory: the second pass is fast
because the reviewer has already read the letter. So the twenty study records are split
into two halves, and each reviewer does one half with proposals and the other half
unaided.

**The halves swap between reviewers.** Reviewer 1 does half A with proposals and half B
unaided; reviewer 2 the reverse. Over any two reviewers every record has been reviewed in
both arms, which is what lets the comparison be made record by record rather than only
between two different sets of documents.

**Everyone starts unaided.** Changed on 2026-10-08 at Peter's direction: a reviewer's
baseline is the work they already do, with nothing the tool provides, so every reviewer
does the unaided half first and the proposals half second. The cost is stated rather than
hidden: the second half benefits from familiarity with the screen and the six document
types, and that is a bias *in the tool's favour*. It used to be balanced by swapping the
order between reviewer pairs. To shrink it, every reviewer does the trial first
(`sever study --trial`), which teaches the screen on two records outside the study, and
each half still opens with an uncounted practice page.

**Each arm starts with a practice page that is not counted.** The first page in a new
interface measures the interface. It is timed and recorded, flagged `practice`, and the
report leaves it out.

**Reviewers are numbered, not named.** The study's files carry `reviewer-1` and never a
name, so the timings and decisions can be committed as evidence without putting a
colleague's name in a public repository.

## What the reviewer is told

The same facts the tool is configured with: who made the request, and the public register.
An unaided reviewer who does not know who the requester is cannot release the requester's
own information, and the comparison would be measuring a missing fact rather than the
tool.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sever.context.register import RegisterEntry
from sever.corpus.labels import LabelledSpan
from sever.decide.pipeline import Proposal, Source
from sever.detect.types import Detection, EntityType
from sever.ingest.document import Offsets
from sever.review.audit import AuditLog
from sever.review.decisions import Origin, final_spans
from sever.review.session import Item, Mode, Session, build_session
from sever.taxonomy.loader import Decision, Provision, Taxonomy

STUDY_DIR = Path("review/study")
STUDY_SEED = 20271001
CORPUS_DOCUMENTS = 210
# Twenty counted pages per reviewer, as PLAN.md section 5 specifies, plus one practice
# page per arm.
STUDY_RECORDS = 20
PRACTICE_RECORDS = 2
# What every reviewer is shown, frozen. See `freeze_proposals`.
STUDY_PROPOSALS = Path("data/study/proposals.jsonl")


@dataclass(frozen=True, slots=True)
class Task:
    """One record in one reviewer's queue."""

    position: int
    doc_id: str
    arm: Mode
    block: int
    practice: bool


@dataclass(frozen=True, slots=True)
class Pool:
    """The records the study draws on: two practice records and two balanced halves."""

    practice: tuple[str, str]
    half_a: tuple[str, ...]
    half_b: tuple[str, ...]

    @property
    def all(self) -> tuple[str, ...]:
        return (*self.practice, *self.half_a, *self.half_b)


def choose_pool(
    candidates: Sequence[tuple[str, str]],
    *,
    seed: int = STUDY_SEED,
    records: int = STUDY_RECORDS,
) -> Pool:
    """Pick the study records from `(doc_id, template)` pairs, balanced by template.

    Each template is dealt alternately into the two halves, so neither half is easier
    because it happened to get more of one kind of document. The draw is seeded, so every
    reviewer, and anyone reproducing the study, gets the same records.
    """
    rng = random.Random(seed)
    by_template: dict[str, list[str]] = {}
    for doc_id, template in candidates:
        by_template.setdefault(template, []).append(doc_id)
    for ids in by_template.values():
        rng.shuffle(ids)
    templates = sorted(by_template)
    dealt: list[str] = []
    while len(dealt) < records + PRACTICE_RECORDS and any(by_template.values()):
        for t in templates:
            if by_template[t] and len(dealt) < records + PRACTICE_RECORDS:
                dealt.append(by_template[t].pop())
    if len(dealt) < records + PRACTICE_RECORDS:
        raise ValueError(
            f"the study needs {records + PRACTICE_RECORDS} records and only {len(dealt)} "
            f"were offered"
        )
    practice = (dealt[0], dealt[1])
    # Grouped by template, then dealt alternately, so each template splits between the
    # halves as evenly as its count allows and the halves are the same size.
    template_of = dict(candidates)
    rest = sorted(dealt[PRACTICE_RECORDS:], key=lambda d: (template_of[d], d))
    return Pool(practice=practice, half_a=tuple(rest[0::2]), half_b=tuple(rest[1::2]))


def plan_for(reviewer: int, pool: Pool, *, seed: int = STUDY_SEED) -> tuple[Task, ...]:
    """The queue for reviewer `reviewer` (numbered from 1).

    Odd and even reviewers swap which half gets proposals, and everyone does the unaided
    half first. See the module docstring for why, and what that costs.
    """
    if reviewer < 1:
        raise ValueError("reviewers are numbered from 1")
    k = reviewer - 1
    aided, unaided = (pool.half_a, pool.half_b) if k % 2 == 0 else (pool.half_b, pool.half_a)
    order = (Mode.UNAIDED, Mode.PROPOSALS)
    rng = random.Random(seed * 1000 + reviewer)
    tasks: list[Task] = []
    for block, arm in enumerate(order, start=1):
        records = list(aided if arm is Mode.PROPOSALS else unaided)
        rng.shuffle(records)
        queue = [(pool.practice[block - 1], True), *((d, False) for d in records)]
        for doc_id, practice in queue:
            tasks.append(
                Task(
                    position=len(tasks) + 1,
                    doc_id=doc_id,
                    arm=arm,
                    block=block,
                    practice=practice,
                )
            )
    return tuple(tasks)


def reviewer_name(reviewer: int) -> str:
    return f"reviewer-{reviewer}"


def reviewer_dir(reviewer: int, root: Path = STUDY_DIR) -> Path:
    return root / reviewer_name(reviewer)


def request_id(reviewer: int) -> str:
    return f"STUDY-{reviewer:02d}"


def enrolled(root: Path = STUDY_DIR) -> tuple[int, ...]:
    """Reviewer numbers that have a folder, in order."""
    if not root.is_dir():
        return ()
    out: list[int] = []
    for p in root.iterdir():
        if p.is_dir() and p.name.startswith("reviewer-"):
            try:
                out.append(int(p.name.removeprefix("reviewer-")))
            except ValueError:
                continue
    return tuple(sorted(out))


@dataclass
class StudyRun:
    """One reviewer's study: their queue, the session behind it, and the reference card."""

    reviewer: int
    tasks: tuple[Task, ...]
    session: Session
    register: tuple[RegisterEntry, ...] = ()

    def done(self, task: Task) -> bool:
        return self.session.releasable(task.doc_id)

    def next_task(self) -> Task | None:
        return next((t for t in self.tasks if not self.done(t)), None)

    def previous(self, task: Task) -> Task | None:
        return self.tasks[task.position - 2] if task.position > 1 else None

    def task(self, doc_id: str) -> Task:
        for t in self.tasks:
            if t.doc_id == doc_id:
                return t
        raise KeyError(doc_id)

    @property
    def completed(self) -> int:
        return sum(1 for t in self.tasks if self.done(t))

    @property
    def finished(self) -> bool:
        return self.next_task() is None


def study_pool(*, seed: int = STUDY_SEED) -> Pool:
    """The study's records, drawn from the corpus test split.

    The test split rather than validation, because the confidence threshold was set on
    validation, and the study should see the tool as it performs on records it was not
    tuned on.
    """
    from sever.corpus.generate import build

    corpus = build(documents=CORPUS_DOCUMENTS)
    return choose_pool([(i.doc_id, i.template) for i in corpus.of_split("test")], seed=seed)


def open_run(reviewer: int, *, root: Path = STUDY_DIR, seed: int = STUDY_SEED) -> StudyRun:
    """Build reviewer `reviewer`'s session, creating their folder on first use.

    Proposals come from the default configuration, rules only, which is what the tool does
    with no flags and so is what a public body would be timing.
    """
    tasks = plan_for(reviewer, study_pool(seed=seed), seed=seed)
    return _run_for(
        tasks,
        folder=reviewer_dir(reviewer, root),
        request=request_id(reviewer),
        actor=reviewer_name(reviewer),
        reviewer=reviewer,
        frozen=shown_proposals(),
    )


def _run_for(
    tasks: tuple[Task, ...],
    *,
    folder: Path,
    request: str,
    actor: str,
    reviewer: int,
    frozen: Mapping[str, tuple[Proposal, ...]] | None = None,
) -> StudyRun:
    from sever.context.register import load_register
    from sever.corpus.generate import build
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.report import config_for

    by_id = {i.doc_id: i for i in build(documents=CORPUS_DOCUMENTS)}
    detector = SeverDetector()
    items: list[Item] = []
    for t in tasks:
        corpus_item = by_id[t.doc_id]
        config = config_for(corpus_item)
        doc = corpus_item.rendered.document
        if frozen is not None:
            proposals = frozen[t.doc_id]
        else:
            proposals = tuple(DecisionEngine(config=config, detector=detector).propose(doc))
        items.append(
            Item(
                document=doc,
                proposals=proposals,
                arm=t.arm,
                practice=t.practice,
                requester=config.requester_name,
            )
        )
    folder.mkdir(parents=True, exist_ok=True)
    session = build_session(
        request_id=request,
        items=items,
        log_path=folder / "audit.duckdb",
        timings_path=folder / "timings.jsonl",
        actor=actor,
    )
    return StudyRun(
        reviewer=reviewer,
        tasks=tasks,
        session=session,
        register=load_register().entries,
    )


def pick_reviewer(root: Path = STUDY_DIR, *, new: bool = False) -> int:
    """Who sits down next, when nobody says.

    The most recent reviewer if they have not finished, so closing the laptop and running
    the same command again resumes where they stopped; otherwise the next number. `new`
    starts the next number regardless.
    """
    numbers = enrolled(root)
    if not numbers:
        return 1
    last = numbers[-1]
    if new:
        return last + 1
    timings = reviewer_dir(last, root) / "timings.jsonl"
    counted = _completed_positions(timings)
    return last if counted < STUDY_RECORDS + PRACTICE_RECORDS else last + 1


def _completed_positions(timings: Path) -> int:
    """Records completed, from the timings file, which is cheap enough to read without
    building the corpus. A page completed after a restart is in the audit log and not
    here, so this can undercount, and an undercount only ever resumes a reviewer who had
    finished, which the session then shows as finished."""
    if not timings.is_file():
        return 0
    docs: set[str] = set()
    for line in timings.read_text(encoding="utf-8").splitlines():
        if line.strip():
            docs.add(str(json.loads(line)["doc_id"]))
    return len(docs)


# --- collecting what the reviewers did -------------------------------------------------

STUDY_RESULTS = Path("results/reviewer-study.jsonl")


@dataclass(frozen=True, slots=True)
class PageResult:
    """One completed study page: how long it took and how right it was.

    The accuracy columns are counted against the corpus labels, which are known by
    construction. A must-redact span is leaked unless every letter and digit of it is
    under a withholding decision, because a surname left beside a severed forename names
    the person. A must-keep span is over-redacted if any letter or digit of it is withheld.
    """

    reviewer: str
    doc_id: str
    arm: str
    practice: bool
    seconds: float | None
    must_redact: int
    leaked: int
    must_keep: int
    over_redacted: int
    added: int
    # The same two counts for the tool's proposals with nobody reviewing them, on the
    # same page, so the table can say whether the reviewer improved on the tool.
    tool_leaked: int
    tool_over_redacted: int
    # Withheld text that no label covers: letters and digits under a box that sit outside
    # every labelled span, such as the word "sibling" beside a severed name. The labels
    # cannot say whether that was right, so it is neither a leak nor an over-redaction; but
    # a reviewer who blacks out a great deal of it is slower and the requester gets less,
    # and without this column that cost would not appear anywhere. Counted in characters
    # and in severances that touch no label at all.
    unlabelled_chars: int = 0
    unlabelled_severances: int = 0
    tool_unlabelled_chars: int = 0
    # Of the leaks, how many were partial and identify nobody: a number with at most four
    # digits showing, or a job title with its role word withheld. See
    # `is_partial_that_identifies_nobody`.
    leaked_fragments: int = 0
    tool_leaked_fragments: int = 0

    def as_json(self) -> dict[str, object]:
        return {
            "reviewer": self.reviewer,
            "doc_id": self.doc_id,
            "page": 1,
            "mode": self.arm,
            "practice": self.practice,
            "seconds": self.seconds,
            "must_redact": self.must_redact,
            "leaked": self.leaked,
            "must_keep": self.must_keep,
            "over_redacted": self.over_redacted,
            "added": self.added,
            "tool_leaked": self.tool_leaked,
            "tool_over_redacted": self.tool_over_redacted,
            "unlabelled_chars": self.unlabelled_chars,
            "unlabelled_severances": self.unlabelled_severances,
            "tool_unlabelled_chars": self.tool_unlabelled_chars,
            "leaked_fragments": self.leaked_fragments,
            "tool_leaked_fragments": self.tool_leaked_fragments,
        }


def _covered(text: str, start: int, end: int, spans: Sequence[tuple[int, int]]) -> tuple[bool, bool]:
    """(every letter and digit covered, any letter or digit covered) for text[start:end]."""
    positions = [i for i in range(start, end) if text[i].isalnum()]
    if not positions:
        return (True, False)
    hit = [any(s <= i < e for s, e in spans) for i in positions]
    return (all(hit), any(hit))


def _unlabelled(
    text: str, labels: Sequence[LabelledSpan], spans: Sequence[tuple[int, int]]
) -> tuple[int, int]:
    """(letters and digits withheld outside every label, severances touching no label)."""
    labelled = {i for lab in labels for i in range(lab.offsets.start, lab.offsets.end)}
    withheld = {i for s, e in spans for i in range(s, e) if text[i].isalnum()}
    loose = sum(
        1
        for s, e in spans
        if not any(i in labelled for i in range(s, e)) and any(text[i].isalnum() for i in range(s, e))
    )
    return len(withheld - labelled), loose


# The most digits of a number that may show for the release of the rest not to identify
# anyone: the convention card masking uses, "**** **** **** 1234". Set on 2026-10-10 after
# reviewer 1 observed that three digits of a twelve-digit MCP number identify nobody, which
# is after the results it changes were seen; that is why the strict count stays beside it.
FRAGMENT_DIGITS = 4


def is_number_fragment(
    text: str, start: int, end: int, spans: Sequence[tuple[int, int]]
) -> bool:
    """True for a leaked span that is a number of nine or more digits with at most
    `FRAGMENT_DIGITS` of them left showing."""
    chars = [i for i in range(start, end) if text[i].isalnum()]
    if len(chars) < 9 or not all(text[i].isdigit() for i in chars):
        return False
    showing = sum(1 for i in chars if not any(s <= i < e for s, e in spans))
    return 0 < showing <= FRAGMENT_DIGITS


def is_title_qualifier(
    text: str, start: int, end: int, spans: Sequence[tuple[int, int]]
) -> bool:
    """True for a leaked job title whose role word is withheld and only its qualifier
    shows: "Access and Privacy" beside a severed "Coordinator", "Corporate Services"
    beside a severed "Manager".

    Reviewer 1's second observation on 2026-10-10: a qualifier names a function or a unit,
    which several people share; it is the position, qualifier and role together, that
    identifies its one holder. The role word is what the job-title recogniser matches
    inside the title. A title the recogniser finds no role word in never qualifies, and nor
    does anything that is not a title: a surname beside a severed forename names someone.
    """
    from sever.detect.recognisers import JOB_TITLE

    title = text[start:end]
    role = JOB_TITLE.pattern.search(title)
    if role is None:
        return False
    role_chars = [start + i for i in range(*role.span()) if title[i].isalnum()]
    return all(any(s <= i < e for s, e in spans) for i in role_chars)


def is_partial_that_identifies_nobody(
    label: LabelledSpan, text: str, spans: Sequence[tuple[int, int]]
) -> bool:
    """A leak the second study column does not count. See the two rules above."""
    start, end = label.offsets.start, label.offsets.end
    if (label.field_name or "").endswith(".title"):
        return is_title_qualifier(text, start, end, spans)
    return is_number_fragment(text, start, end, spans)


def _count(
    text: str, labels: Sequence[LabelledSpan], spans: Sequence[tuple[int, int]], taxonomy: Taxonomy
) -> tuple[int, int, int, int, int]:
    must_redact = leaked = must_keep = over = fragments = 0
    for label in labels:
        start, end = label.offsets.start, label.offsets.end
        full, touched = _covered(text, start, end, spans)
        if taxonomy.decision(label.code).withholds:
            must_redact += 1
            if not full:
                leaked += 1
                fragments += 1 if is_partial_that_identifies_nobody(label, text, spans) else 0
        else:
            must_keep += 1
            over += 1 if touched else 0
    return must_redact, leaked, must_keep, over, fragments


def collect(root: Path = STUDY_DIR, *, seed: int = STUDY_SEED) -> tuple[PageResult, ...]:
    """Every completed page of every reviewer, scored against the frozen proposals.

    Reads each reviewer's audit log, which is the record of what they decided, and their
    timings file, which is the record of how long it took. A completed page with no timing
    is kept with `seconds` empty, so the untimed pages stay visible rather than dropping
    out of the denominator.
    """
    from sever.corpus.generate import build
    from sever.taxonomy.loader import default_taxonomy

    taxonomy = default_taxonomy()
    corpus = {i.doc_id: i for i in build(documents=CORPUS_DOCUMENTS)}
    # What the reviewers were shown, not what the tool would propose today: a page is
    # scored against the proposals on the screen when it was decided.
    tool = shown_proposals()
    out: list[PageResult] = []
    for number in enrolled(root):
        folder = reviewer_dir(number, root)
        if not (folder / "audit.duckdb").is_file():
            continue
        seconds: dict[str, float] = {}
        timings = folder / "timings.jsonl"
        if timings.is_file():
            for line in timings.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    seconds[str(d["doc_id"])] = seconds.get(str(d["doc_id"]), 0.0) + float(
                        d["seconds"]
                    )
        with AuditLog(folder / "audit.duckdb") as log:
            rows = log.rows(request_id=request_id(number))
            done = log.pages_reviewed(request_id(number))
        for task in plan_for(number, study_pool(seed=seed), seed=seed):
            if (task.doc_id, 1) not in done:
                continue
            item = corpus[task.doc_id]
            doc = item.rendered.document
            proposals = tool[task.doc_id] if task.arm.shows_proposals else ()
            final = final_spans(rows, proposals, doc_id=task.doc_id, taxonomy=taxonomy)
            text = doc.page(1).text
            labels = item.rendered.labels.on_page(1)
            reviewed = [(s.start, s.end) for s in final if s.withholds and s.page == 1]
            unreviewed = [
                (p.detection.offsets.start, p.detection.offsets.end)
                for p in tool[task.doc_id]
                if p.withholds and p.page == 1
            ]
            mr, lk, mk, ov, fr = _count(text, labels, reviewed, taxonomy)
            _, tlk, _, tov, tfr = _count(text, labels, unreviewed, taxonomy)
            loose_chars, loose_cuts = _unlabelled(text, labels, reviewed)
            tool_loose, _ = _unlabelled(text, labels, unreviewed)
            out.append(
                PageResult(
                    reviewer=reviewer_name(number),
                    doc_id=task.doc_id,
                    arm=task.arm.value,
                    practice=task.practice,
                    seconds=round(seconds[task.doc_id], 3) if task.doc_id in seconds else None,
                    must_redact=mr,
                    leaked=lk,
                    must_keep=mk,
                    over_redacted=ov,
                    added=sum(1 for s in final if s.origin is Origin.REVIEWER and s.withholds),
                    tool_leaked=tlk,
                    tool_over_redacted=tov,
                    unlabelled_chars=loose_chars,
                    unlabelled_severances=loose_cuts,
                    tool_unlabelled_chars=tool_loose,
                    leaked_fragments=fr,
                    tool_leaked_fragments=tfr,
                )
            )
    return tuple(out)


def write_results(results: Sequence[PageResult], path: Path = STUDY_RESULTS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r.as_json(), sort_keys=True) + "\n" for r in results),
        encoding="utf-8",
    )
    return path


# --- what the reviewers are shown, frozen ----------------------------------------------
#
# The first real run (2026-10-10) found a detector defect: the SIN recogniser claimed the
# first nine digits of a twelve-digit MCP number and the last three were proposed for
# release. Fixing it changes the proposals, and until then `collect` recomputed proposals
# from whatever the code was on the day it ran. A fix would have rescored reviewer 1's
# pages against proposals they never saw, crediting them with the fix, and reviewer 2 would
# have been shown a different tool from reviewer 1. So the proposals for the study's
# records are written down once, from the code reviewer 1 used (commit d2d6d3d), and both
# the screen and the scoring read them. The headline tables use the current tool; the
# study measures one fixed tool across every reviewer, and says which.


def _proposal_json(doc_id: str, p: Proposal) -> dict[str, object]:
    d = p.detection
    return {
        "doc_id": doc_id,
        "page": d.page,
        "start": d.offsets.start,
        "end": d.offsets.end,
        "text": d.text,
        "entity_type": d.entity_type.value,
        "score": d.score,
        "recogniser": d.recogniser,
        "code": p.code,
        "decision": p.decision.value,
        "confidence": p.confidence,
        "reason": p.reason,
        "source": p.source.value,
        "rule": p.rule,
        "provisions": [pr.model_dump(mode="json") for pr in p.provisions],
        "disagreement": p.disagreement,
    }


def _proposal_from(d: Mapping[str, object]) -> Proposal:
    raw_provisions = d["provisions"]
    assert isinstance(raw_provisions, list)
    return Proposal(
        detection=Detection(
            page=int(str(d["page"])),
            offsets=Offsets(int(str(d["start"])), int(str(d["end"]))),
            text=str(d["text"]),
            entity_type=EntityType(str(d["entity_type"])),
            score=float(str(d["score"])),
            recogniser=str(d["recogniser"]),
        ),
        code=str(d["code"]),
        decision=Decision(str(d["decision"])),
        confidence=float(str(d["confidence"])),
        reason=str(d["reason"]),
        source=Source(str(d["source"])),
        rule=None if d["rule"] is None else str(d["rule"]),
        provisions=tuple(Provision.model_validate(x) for x in raw_provisions),
        disagreement=None if d["disagreement"] is None else str(d["disagreement"]),
    )


def freeze_proposals(path: Path = STUDY_PROPOSALS, *, seed: int = STUDY_SEED) -> Path:
    """Write the current tool's rules-only proposals for every study record."""
    from sever.corpus.generate import build
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.report import config_for

    corpus = {i.doc_id: i for i in build(documents=CORPUS_DOCUMENTS)}
    detector = SeverDetector()
    lines: list[str] = []
    for doc_id in study_pool(seed=seed).all:
        item = corpus[doc_id]
        engine = DecisionEngine(config=config_for(item), detector=detector)
        for p in engine.propose(item.rendered.document):
            lines.append(json.dumps(_proposal_json(doc_id, p), sort_keys=True) + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


def shown_proposals(
    path: Path = STUDY_PROPOSALS, *, seed: int = STUDY_SEED
) -> dict[str, tuple[Proposal, ...]]:
    """The frozen proposals, by record. Every study record must be present: a record
    missing from the file would otherwise be shown with no proposals at all."""
    out: dict[str, list[Proposal]] = {doc_id: [] for doc_id in study_pool(seed=seed).all}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out.setdefault(str(d["doc_id"]), []).append(_proposal_from(d))
    empty = sorted(doc_id for doc_id, ps in out.items() if not ps)
    if empty:
        raise ValueError(f"{path} has no proposals for {', '.join(empty)}")
    return {doc_id: tuple(ps) for doc_id, ps in out.items()}


# --- the trial: learning the screen, outside the study ---------------------------------

TRIAL_DIR = Path("review/trial")


def trial_records(*, seed: int = STUDY_SEED) -> tuple[str, str]:
    """Two test-split records the study never uses, of two different document types."""
    from sever.corpus.generate import build

    corpus = build(documents=CORPUS_DOCUMENTS)
    used = set(study_pool(seed=seed).all)
    picked: list[str] = []
    templates: set[str] = set()
    for item in corpus.of_split("test"):
        if item.doc_id in used or item.template in templates:
            continue
        picked.append(item.doc_id)
        templates.add(item.template)
        if len(picked) == 2:
            return (picked[0], picked[1])
    raise ValueError("the test split has no two unused records of different types")


def open_trial(root: Path = TRIAL_DIR) -> StudyRun:
    """A fresh trial run: one record without proposals, then one with, never scored.

    Asked for after the first reviewer's run had to be discarded because it was spent
    learning the screen. The trial is where that learning goes. It starts clean every
    time, its folder is not one `collect` reads, and its actor is "trial".
    """
    import shutil

    shutil.rmtree(root, ignore_errors=True)
    unaided, aided = trial_records()
    tasks = (
        Task(position=1, doc_id=unaided, arm=Mode.UNAIDED, block=1, practice=True),
        Task(position=2, doc_id=aided, arm=Mode.PROPOSALS, block=2, practice=True),
    )
    return _run_for(tasks, folder=root, request="TRIAL", actor="trial", reviewer=0)
