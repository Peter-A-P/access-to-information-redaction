"""The reviewer's screen: one page at a time, an action on every span, a log of all of it.

This is the part of the project that has to exist for the first claim in the README to be
true. "The tool proposes; a person decides" is a statement about an interface, and until
there is one the claim is about code that nobody can drive.

## What it is, and what it is not

Server-rendered HTML. No build step, no bundler, no client framework, no JSON API and no
script fetched from anywhere: the reviewer's actions are form posts, the server answers with
the piece of the page that changed, and about thirty lines of hand-written JavaScript in
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
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sever.decide.pipeline import Proposal
from sever.ingest.document import Page
from sever.review.audit import Action
from sever.review.session import NotReviewed, Session

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

    @property
    def is_span(self) -> bool:
        return self.proposal is not None

    @property
    def span_id(self) -> str:
        p = self.proposal
        if p is None:
            return ""
        return f"s{p.detection.offsets.start}-{p.detection.offsets.end}"

    @property
    def state(self) -> str:
        """The CSS class, and the word the reviewer reads."""
        if self.acted is None:
            return "pending"
        return self.acted.value


def fragments(
    page: Page, proposals: Sequence[Proposal], acted: dict[tuple[int, int], Action]
) -> tuple[Fragment, ...]:
    """Cut the page text at the span boundaries.

    Overlapping proposals are not expected and are not rendered twice: the later one is
    dropped rather than allowed to produce interleaved markup, because a reviewer looking
    at broken highlighting cannot tell which span they are acting on.
    """
    out: list[Fragment] = []
    cursor = 0
    for p in sorted(proposals, key=lambda p: p.detection.offsets.start):
        start, end = p.detection.offsets.start, p.detection.offsets.end
        if start < cursor:
            continue
        if start > cursor:
            out.append(Fragment(text=page.text[cursor:start]))
        out.append(
            Fragment(text=page.text[start:end], proposal=p, acted=acted.get((start, end)))
        )
        cursor = end
    if cursor < len(page.text):
        out.append(Fragment(text=page.text[cursor:]))
    return tuple(out)


def create_app(session: Session) -> FastAPI:
    """The application, over one session. A session per process, deliberately."""
    app = FastAPI(title="sever review", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES))
    templates.env.globals["session"] = session
    templates.env.globals["span_actions"] = SPAN_ACTIONS

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
        return {
            "item": item,
            "page": page,
            "fragments": fragments(page, proposals, acted),
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
        if proposal is None and chosen is not Action.ADD:
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
        approvals = [
            r for r in session.log.approvals(session.request_id) if r.doc_id == doc_id
        ]
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
