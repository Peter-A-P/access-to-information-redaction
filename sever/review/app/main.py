"""The reviewer's screen: one page at a time, an action on every span, a log of all of it.

This is the part of the project that has to exist for the first claim in the README to be
true. "The tool proposes; a person decides" is a statement about an interface, and until
there is one the claim is about code that nobody can drive.

## What it is, and what it is not

Server-rendered HTML. No build step, no bundler, no client framework, no JSON API and no
script fetched from anywhere: the reviewer's actions are form posts, the server answers with
the piece of the page that changed, and about a hundred lines of hand-written JavaScript in
`base.html` do the swap. That is not nostalgia. The audit log is the point of this
application, and every state change here is a row in it, so an architecture where the server
sees each action individually is the one that matches what has to be recorded. PLAN.md said
htmx and PLAN 12.16 records why it is not here: a tool for reading government records should
run with the network cable out.

There is no authentication and no multi-user support. The session is one reviewer on one
machine, which is what the time study needs and what a demonstration needs. Anything more
would be a claim about deployment that this project has not earned.

## The rules this file enforces

  * **Every span gets an action.** The completion button for a page is refused while any
    span on it is untouched, and the refusal names them.
  * **Every page gets a completion.** Export asks `Session.release_gate`, which raises.
  * **Nothing is edited.** A reviewer who changes their mind posts another action, and the
    log keeps both. The interface shows the latest, the log shows the history.
  * **The reviewer can add what the tool missed.** Detection recall is 98.6 percent, so a
    reviewer who can only accept or reject the tool's list inherits its misses with no way
    to fix them. Selecting text on the page and giving it a category posts an `ADD`.

## Why the page text is rendered as characters and not as a PDF

Every offset in this system indexes `Page.text`, and the export computes its rectangles from
those offsets. Rendering the same string here, with the same offsets, means the reviewer is
looking at the thing the redaction will be applied to. A PDF viewer with an overlay would
introduce a second coordinate system and a second chance to be wrong about which characters
are covered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sever.decide.pipeline import Proposal
from sever.ingest.document import Page
from sever.review.audit import Action
from sever.review.decisions import FinalSpan
from sever.review.session import NotReviewed, Session

if TYPE_CHECKING:
    from sever.review.study import StudyRun

TEMPLATES = Path(__file__).parent / "templates"

# What a reviewer can do to a span, and what the button says. Kept here rather than in the
# template so that the set the interface offers is the set the audit log understands: a
# button posting an action the log has no member for is a 500 at best and a silent
# mis-record at worst.
SPAN_ACTIONS: tuple[tuple[Action, str, str], ...] = (
    (Action.APPROVE, "Withhold", "Accept the proposal and sever this span"),
    (Action.REJECT, "Release", "Reject the proposal and leave this span in the record"),
    (Action.ESCALATE, "Escalate", "Withhold it and send it up: this one needs a decision"),
)


@dataclass(frozen=True, slots=True)
class Fragment:
    """One piece of a rendered page: either plain text or a span under review."""

    text: str
    proposal: Proposal | None = None
    acted: Action | None = None
    # A severance the reviewer made that the tool never proposed.
    added: FinalSpan | None = None

    @property
    def is_span(self) -> bool:
        return self.proposal is not None

    @property
    def is_added(self) -> bool:
        return self.added is not None

    @property
    def span_id(self) -> str:
        if self.added is not None:
            return f"s{self.added.start}-{self.added.end}"
        p = self.proposal
        if p is None:
            return ""
        return f"s{p.detection.offsets.start}-{p.detection.offsets.end}"

    @property
    def state(self) -> str:
        """The CSS class, and the word the reviewer reads."""
        if self.added is not None:
            return Action.ADD.value
        if self.acted is None:
            return "pending"
        return self.acted.value


def fragments(
    page: Page,
    proposals: Sequence[Proposal],
    acted: dict[tuple[int, int], Action],
    added: Sequence[FinalSpan] = (),
) -> tuple[Fragment, ...]:
    """Cut the page text at the span boundaries.

    Overlapping spans are not expected and are not rendered twice: the later one is
    dropped rather than allowed to produce interleaved markup, because a reviewer looking
    at broken highlighting cannot tell which span they are acting on. A reviewer's own
    severance that overlaps a proposal is still in the list under the record and still
    applied by the export; only its highlight gives way.
    """
    marks: list[tuple[int, int, Proposal | None, FinalSpan | None]] = [
        (p.detection.offsets.start, p.detection.offsets.end, p, None) for p in proposals
    ]
    marks += [(a.start, a.end, None, a) for a in added]
    out: list[Fragment] = []
    cursor = 0
    for start, end, p, a in sorted(marks, key=lambda m: (m[0], m[1])):
        if start < cursor:
            continue
        if start > cursor:
            out.append(Fragment(text=page.text[cursor:start]))
        out.append(
            Fragment(
                text=page.text[start:end],
                proposal=p,
                acted=acted.get((start, end)) if p is not None else None,
                added=a,
            )
        )
        cursor = end
    if cursor < len(page.text):
        out.append(Fragment(text=page.text[cursor:]))
    return tuple(out)


BULK_RELEASE_REASON = "released with every other undecided span on the page, in one action"

_GROUPS = (("redact", "Withhold"), ("keep", "Release"), ("escalate", "Withhold and escalate"))


def _code_groups(session: Session) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    for decision, label in _GROUPS:
        codes = [
            c.code
            for c in session.taxonomy.categories
            if session.taxonomy.decision(c.code, session.jurisdiction).value == decision
        ]
        if codes:
            out.append((label, codes))
    return out


def create_app(
    session: Session, study: StudyRun | None = None, *, demo: bool = False
) -> FastAPI:
    """The application, over one session. A session per process, deliberately.

    With `study`, the same screens run the reviewer time study: a welcome page, one record
    after another in the order the study chose, a pause where the arm changes, and no index
    or audit-log links to wander off through. See `sever.review.study`.

    With `demo`, it is one visitor's session in the public demonstration: a banner says the
    records are invented and nothing is kept, and a released record offers its redacted
    PDF. See `sever.review.demo`.
    """
    app = FastAPI(title="sever review", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES))
    templates.env.globals["session"] = session
    templates.env.globals["span_actions"] = SPAN_ACTIONS
    templates.env.globals["study"] = study
    templates.env.globals["demo"] = demo
    if study is not None:
        _study_routes(app, templates, study)

    def _page_context(doc_id: str, number: int) -> dict[str, Any]:
        try:
            item = session.item(doc_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no document {doc_id}") from None
        if not 1 <= number <= len(item.document):
            raise HTTPException(status_code=404, detail=f"{doc_id} has no page {number}")
        page = item.document.page(number)
        acted = session.acted_spans(doc_id, number)
        proposals = item.on_page(number)
        added = session.added_spans(doc_id, number)
        withholding = [
            c.code
            for c in session.taxonomy.categories
            if session.taxonomy.decision(c.code, session.jurisdiction).withholds
        ]
        return {
            "item": item,
            "page": page,
            "mode": session.mode_of(doc_id),
            "task": study.task(doc_id) if study is not None else None,
            "added": added,
            # What each span ends up as after the reviewer's latest action, so a decided
            # span is drawn as withheld or released by what it does, not by which button
            # was pressed: a span moved to a keep category is released.
            "final": {(f.start, f.end): f for f in session.final_spans(doc_id) if f.page == number},
            # What a reviewer can sever a span under. A keep code here would offer to
            # withhold a span as "the requester's own information", which means nothing.
            # R1 first, because it is what an added span almost always is.
            "add_codes": sorted(withholding, key=lambda c: (c != "R1", c)),
            # Every code a reviewer may move a span to, grouped by what it does to the
            # span, so the choice reads "Release: an official acting in their capacity"
            # rather than "K2". Flag-only codes are left out: they make no decision.
            "code_groups": _code_groups(session),
            "fragments": fragments(page, proposals, acted, added),
            "proposals": proposals,
            "acted": acted,
            "outstanding": session.outstanding(doc_id, number),
            "complete": session.page_complete(doc_id, number),
            "pages": len(item.document),
            "codes": sorted(c.code for c in session.taxonomy.categories),
            "taxonomy": session.taxonomy,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        rows = [
            {
                "doc_id": i.doc_id,
                "doc_type": i.document.doc_type.value,
                "pages": len(i.document),
                "remaining": session.pages_remaining(i.doc_id),
                "proposals": len(i.proposals),
            }
            for i in session
        ]
        return templates.TemplateResponse(request, "index.html", {"rows": rows})

    @app.get("/doc/{doc_id}/page/{number}", response_class=HTMLResponse)
    def page_view(request: Request, doc_id: str, number: int) -> Any:
        ctx = _page_context(doc_id, number)
        # Stamped on the way out, not on the way in, so the clock starts when the page is
        # rendered rather than when a partial fragment is fetched.
        session.serve(doc_id, number)
        return templates.TemplateResponse(request, "page.html", ctx)

    @app.post("/doc/{doc_id}/page/{number}/span", response_class=HTMLResponse)
    def act_on_span(
        request: Request,
        doc_id: str,
        number: int,
        start: int = Form(...),
        end: int = Form(...),
        action: str = Form(...),
        code: str = Form(""),
        reason: str = Form(""),
    ) -> Any:
        item = session.item(doc_id)
        page = item.document.page(number)
        try:
            chosen = Action(action)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"unknown action {action!r}") from None
        if chosen not in {a for a, _, _ in SPAN_ACTIONS} | {Action.CHANGE_CATEGORY, Action.ADD}:
            raise HTTPException(status_code=400, detail=f"{action!r} is not a span action")
        proposal = next(
            (
                p
                for p in item.on_page(number)
                if (p.detection.offsets.start, p.detection.offsets.end) == (start, end)
            ),
            None,
        )
        is_undo = (
            proposal is None
            and chosen is Action.REJECT
            and any((a.start, a.end) == (start, end) for a in session.added_spans(doc_id, number))
        )
        if proposal is None and chosen is not Action.ADD and not is_undo:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"there is no proposal at {start}-{end} on {doc_id} page {number}. "
                    f"A span the tool did not propose is added, not approved."
                ),
            )
        if chosen in (Action.ADD, Action.CHANGE_CATEGORY) and not code:
            raise HTTPException(status_code=400, detail="that action needs a category")
        if code and code not in {c.code for c in session.taxonomy.categories}:
            raise HTTPException(status_code=400, detail=f"unknown category {code!r}")
        final = code or (proposal.code if proposal is not None else None)
        session.record(
            doc_id=doc_id,
            page=number,
            action=chosen,
            span_start=start,
            span_end=end,
            span_text=page.text[start:end],
            proposed_code=proposal.code if proposal is not None else None,
            final_code=final if chosen is not Action.REJECT else None,
            reason=reason or None,
        )
        return templates.TemplateResponse(request, "_page_body.html", _page_context(doc_id, number))

    @app.post("/doc/{doc_id}/page/{number}/release-rest", response_class=HTMLResponse)
    def release_rest(request: Request, doc_id: str, number: int) -> Any:
        """Release every span on the page the reviewer has not decided yet.

        Asked for by the first reviewer, because a page can carry thirty spans and most of
        what is left after the third parties are withheld is officials, places and dates.
        It is still a person's decision about every span: one REJECT row per span, each
        with the same reason, so the log says these were released in one action rather
        than one at a time, and the reviewer study can tell the two apart. The button asks
        first and says how many of the spans the tool had proposed to withhold.
        """
        item = session.item(doc_id)
        page = item.document.page(number)
        for p in session.outstanding(doc_id, number):
            o = p.detection.offsets
            session.record(
                doc_id=doc_id,
                page=number,
                action=Action.REJECT,
                span_start=o.start,
                span_end=o.end,
                span_text=page.text[o.start : o.end],
                proposed_code=p.code,
                final_code=None,
                reason=BULK_RELEASE_REASON,
            )
        return templates.TemplateResponse(request, "_page_body.html", _page_context(doc_id, number))

    @app.post("/doc/{doc_id}/page/{number}/complete", response_class=HTMLResponse)
    def complete(request: Request, doc_id: str, number: int) -> Any:
        outstanding = session.outstanding(doc_id, number)
        if outstanding:
            ctx = _page_context(doc_id, number)
            ctx["error"] = (
                f"{len(outstanding)} span(s) on this page have no decision yet: "
                + ", ".join(repr(p.detection.text) for p in outstanding[:5])
                + ". A page is complete when a person has said something about every span "
                "on it."
            )
            return templates.TemplateResponse(request, "_page_body.html", ctx)
        session.complete_page(doc_id, number)
        return templates.TemplateResponse(request, "_page_body.html", _page_context(doc_id, number))

    @app.post("/doc/{doc_id}/release")
    def release(doc_id: str) -> Any:
        """Ask the gate. This endpoint does not decide, it asks the thing that decides."""
        try:
            session.release_gate(doc_id)
        except NotReviewed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url=f"/doc/{doc_id}/released", status_code=303)

    @app.get("/doc/{doc_id}/released", response_class=HTMLResponse)
    def released(request: Request, doc_id: str) -> Any:
        # Asked again on the way in rather than trusted from the redirect, because this URL
        # can be typed, bookmarked or reloaded after the log has been added to, and the
        # only safe answer to "may this be released" is the one given at the moment of
        # asking.
        try:
            session.release_gate(doc_id)
        except NotReviewed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        item = session.item(doc_id)
        # The latest row for every span the reviewer's decisions withhold. Read through
        # `final_spans` rather than `AuditLog.approvals`, because a span moved from R1 to
        # R2 is withheld by a CHANGE_CATEGORY row, which only the taxonomy can tell apart
        # from one moved to K2.
        kept = {s.key for s in session.final_spans(doc_id) if s.withholds}
        latest: dict[tuple[int, int, int], Any] = {}
        for r in session.log.rows(request_id=session.request_id):
            if r.action in (Action.COMMENT, Action.PAGE_COMPLETE):
                continue
            if r.doc_id == doc_id and r.span_start is not None and r.span_end is not None:
                latest[(r.page, r.span_start, r.span_end)] = r
        approvals = [r for k, r in sorted(latest.items()) if k in kept]
        return templates.TemplateResponse(
            request,
            "released.html",
            {"item": item, "approvals": approvals, "count": len(approvals)},
        )

    @app.get("/log", response_class=HTMLResponse)
    def log_view(request: Request) -> Any:
        ok, message = session.log.verify_chain()
        return templates.TemplateResponse(
            request,
            "log.html",
            {"rows": session.log.rows(request_id=session.request_id), "ok": ok, "message": message},
        )

    return app


def _study_routes(app: FastAPI, templates: Jinja2Templates, study: StudyRun) -> None:
    """The study's own screens. Registered before the ordinary ones, so `/` is the
    welcome page rather than the document index."""

    @app.get("/", response_class=HTMLResponse)
    def welcome(request: Request) -> Any:
        if study.completed:
            return RedirectResponse(url="/next", status_code=303)
        return templates.TemplateResponse(request, "study_welcome.html", {})

    @app.get("/next", response_class=HTMLResponse)
    def next_record(request: Request) -> Any:
        task = study.next_task()
        if task is None:
            return templates.TemplateResponse(request, "study_done.html", {})
        before = study.previous(task)
        if before is not None and before.arm is not task.arm and study.done(before):
            # The arm changes here. A pause, and the instructions for the other arm,
            # before the clock starts on a page.
            return templates.TemplateResponse(request, "study_break.html", {"task": task})
        return RedirectResponse(url=f"/doc/{task.doc_id}/page/1", status_code=303)
