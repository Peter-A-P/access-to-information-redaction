"""The public demonstration: the reviewer's screen, one private session per visitor.

`sever review` is one reviewer on one machine, bound to loopback with no authentication,
and that is right for it. A public demonstration needs two things it does not have: a
visitor must not see another visitor's decisions, and nothing a visitor does may be kept.
This module adds exactly those and nothing else. Every screen is the reviewer's own
screen, every rule is the same rule, and the release gate is the same gate.

**One session per visitor, forgotten.** A visitor gets a random cookie and a session of
their own over the same records (six synthetic ones, and the released pages below), with an audit log in a temporary file that
is deleted when the session is evicted: after `IDLE` without a request, or when more than
`MAX_SESSIONS` are live, oldest first. Nothing is logged about the visitor and nothing is
written anywhere that outlives the process.

**Rules only.** No model is called, so the demonstration costs nothing to run and cannot
be made to spend money. The records are generated from a seed at start.

**The redacted PDF is real.** A visitor who completes a record can download it, built from
their own decisions by the same export that `sever export` uses, with the leak test run on
it before it is served. That is the one claim worth demonstrating that a screenshot cannot.

**Pages a public body released** (PLAN.md 12.46). Ten short excerpts of published LAC
packages, built by `sever demo-records` into `data/demo` and read by `released_items`, sit
beside the invented records. Their PDF is LAC's own scan with the boxes burned into the
page image (`redact_scan`), and the leak test adds the two checks a scan needs: the image's
own pixels under every box, and the file's structure. The dashboard counts decisions on
them apart, since everything visible on them was already released by a person.

**The website and the dashboard are served without a session.** The project's site (built
by `sever.site` into `site`) is at `/`, `/how` and their files; the live dashboard is
`/dashboard`, reading `/dashboard.json`, the counts `sever.review.stats` keeps across every
visitor. Neither sets a cookie: a visitor is given a session the first time they open the
reviewer's screen, at `/review`, and not for reading about it.
"""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from sever.review.session import Item, Mode, Session, build_session
from sever.review.stats import DemoStats, tool_counts

COOKIE = "sever_demo"
IDLE = 2 * 60 * 60
MAX_SESSIONS = 200
DEMO_DOCUMENTS = 6
DEMO_REQUEST = "DEMO-2026"

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def demo_items(documents: int = DEMO_DOCUMENTS) -> tuple[Item, ...]:
    """One record of each document type, with the tool's rules-only proposals."""
    from sever.corpus.generate import build
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.report import config_for

    detector = SeverDetector()
    items: list[Item] = []
    for corpus_item in build(documents=documents):
        config = config_for(corpus_item)
        doc = corpus_item.rendered.document
        proposals = DecisionEngine(config=config, detector=detector).propose(doc)
        items.append(
            Item(document=doc, proposals=tuple(proposals), requester=config.requester_name)
        )
    return tuple(items)


def released_items(
    manifest: Path | None = None, directory: Path | None = None
) -> tuple[Item, ...]:
    """The pages a public body has already released (`data/demo`), with the tool's
    rules-only proposals, configured as `sever eval-releases` configures them: no
    requester, and the archival rule for an archives' release, counted from the year the
    package was retrieved."""
    from sever.context.requester import RequestConfig
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.ingest import excerpts

    detector = SeverDetector()
    directory = directory or excerpts.DEFAULT_DIR
    items: list[Item] = []
    for record in excerpts.read_manifest(manifest or excerpts.DEFAULT_MANIFEST):
        document = excerpts.load(record, directory)
        config = RequestConfig(
            request_id=record.doc_id,
            archival=record.archival,
            as_of_year=int(record.retrieved_on[:4]),
        )
        proposals = DecisionEngine(config=config, detector=detector).propose(document)
        items.append(
            Item(
                document=document,
                proposals=tuple(proposals),
                released=replace(record, pdf=directory / record.file_name),
            )
        )
    return tuple(items)


@dataclass
class _Visitor:
    session: Session
    app: ASGIApp
    folder: Path
    seen: float


# The site's pages by the path they are served at, and the content types of its files.
PAGES = {"/": "index.html", "/index.html": "index.html", "/how": "how.html",
         "/dashboard": "dashboard.html"}
_ASSET = re.compile(r"^/(?:[a-z]+\.(?:css|js)|fonts/[A-Za-z0-9-]+\.(?:woff2|txt)|data/site\.json)$")


@dataclass(frozen=True, slots=True)
class _File:
    body: bytes
    content_type: str
    cache: str


def load_site(directory: Path) -> dict[str, _File]:
    """Every file of the built site, in memory, by the path it is served at. The site is a
    few hundred kilobytes and never changes while the process runs."""
    files: dict[str, _File] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        rel = "/" + path.relative_to(directory).as_posix()
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".woff2":
            kind = "font/woff2"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind += "; charset=utf-8"
        cache = "no-cache" if path.suffix in (".html", ".json") else "public, max-age=3600"
        files[rel] = _File(path.read_bytes(), kind, cache)
    for route, name in PAGES.items():
        if f"/{name}" not in files:
            raise FileNotFoundError(f"the built site has no {name}; run `sever site`")
        files[route] = files[f"/{name}"]
    return files


@dataclass
class DemoServer:
    """The ASGI application: the website and dashboard for everyone, and each visitor's
    own reviewer app for the rest."""

    items: Sequence[Item]
    site: Path | None = None
    idle: float = IDLE
    max_sessions: int = MAX_SESSIONS
    clock: Callable[[], float] = time.monotonic
    secure_cookie: bool = True
    stats: DemoStats | None = None
    _visitors: OrderedDict[str, _Visitor] = field(default_factory=OrderedDict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _files: dict[str, _File] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.stats is None:
            from sever.taxonomy.loader import default_taxonomy

            taxonomy = default_taxonomy()
            self.stats = DemoStats(
                taxonomy=taxonomy,
                tool=tool_counts([i for i in self.items if i.released is None], taxonomy),
                tool_released=tool_counts(
                    [i for i in self.items if i.released is not None], taxonomy
                ),
            )
        if self.site is not None:
            self._files = load_site(self.site)

    def __len__(self) -> int:
        return len(self._visitors)

    def _evict(self, now: float) -> None:
        while self._visitors:
            key, oldest = next(iter(self._visitors.items()))
            if now - oldest.seen < self.idle and len(self._visitors) <= self.max_sessions:
                break
            del self._visitors[key]
            oldest.session.log.close()
            shutil.rmtree(oldest.folder, ignore_errors=True)

    def _new_visitor(self, now: float) -> tuple[str, _Visitor]:
        key = secrets.token_urlsafe(24)
        folder = Path(tempfile.mkdtemp(prefix="sever-demo-"))
        session = build_session(
            request_id=DEMO_REQUEST,
            items=self.items,
            log_path=folder / "audit.duckdb",
            mode=Mode.PROPOSALS,
            actor="visitor",
        )
        stats = self.stats
        assert stats is not None
        session.observer = stats.observe
        stats.visitor()
        visitor = _Visitor(
            session=session, app=_visitor_app(session, stats), folder=folder, seen=now
        )
        return key, visitor

    def live(self) -> int:
        """Sessions not yet evicted: active in the last `idle` seconds."""
        with self._lock:
            self._evict(self.clock())
            return len(self._visitors)

    def visitor(self, key: str | None) -> tuple[str, _Visitor, bool]:
        """The visitor for a cookie value, or a new one. True when it was created."""
        now = self.clock()
        with self._lock:
            self._evict(now)
            if key is not None and key in self._visitors:
                v = self._visitors.pop(key)
                v.seen = now
                self._visitors[key] = v
                return key, v, False
            key, v = self._new_visitor(now)
            self._visitors[key] = v
            self._evict(now)
            return key, v, True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        path = scope.get("path", "/")
        if path == "/healthz":
            await _plain(send, 200, b"ok")
            return
        if path == "/dashboard.json":
            assert self.stats is not None
            body = json.dumps(self.stats.snapshot(live=self.live())).encode()
            await _send(send, 200, body, "application/json", "no-store")
            return
        if path in self._files or (self._files and _ASSET.match(path)):
            if scope.get("method") not in ("GET", "HEAD"):
                await _plain(send, 405, b"method not allowed")
                return
            f = self._files.get(path)
            if f is None:
                await _plain(send, 404, b"not found")
                return
            await _send(send, 200, f.body, f.content_type, f.cache)
            return
        key, visitor, created = self.visitor(_cookie(scope, COOKIE))
        if not created:
            await visitor.app(scope, receive, send)
            return
        # A new visitor: set the cookie and send them where they asked to go, so the
        # first request after the cookie is set is the one that reaches their session.
        flags = "; Secure" if self.secure_cookie else ""
        location = path if scope.get("method") == "GET" else "/review"
        await send(
            {
                "type": "http.response.start",
                "status": 303,
                "headers": [
                    (b"location", location.encode()),
                    (
                        b"set-cookie",
                        f"{COOKIE}={key}; Path=/; HttpOnly; SameSite=Lax; Max-Age={int(self.idle)}{flags}".encode(),
                    ),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def _visitor_app(session: Session, stats: DemoStats | None = None) -> ASGIApp:
    from sever.review.app import create_app

    app = create_app(session, demo=True)
    _add_pdf_route(app, session, stats)
    return app


def _add_pdf_route(app: FastAPI, session: Session, stats: DemoStats | None = None) -> None:
    @app.get("/doc/{doc_id}/released.pdf")
    def released_pdf(doc_id: str) -> Response:
        """The visitor's own decisions, truly redacted, leak-tested before it is served."""
        from sever.eval.pdf_leak import LeakChecker
        from sever.review.decisions import as_released
        from sever.review.export import UnplacedSpan, apply_redactions, redact_scan, render_pdf
        from sever.review.session import NotReviewed

        try:
            session.release_gate(doc_id)
        except NotReviewed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no document {doc_id}") from None
        item = session.item(doc_id)
        applied = as_released(
            session.final_spans(doc_id),
            item.proposals,
            item.document,
            taxonomy=session.taxonomy,
        )
        scan = item.released.pdf if item.released is not None else None
        with tempfile.TemporaryDirectory(prefix="sever-demo-pdf-") as tmp:
            out = Path(tmp) / "released.pdf"
            if scan is not None:
                # A published release: the boxes go on LAC's own page images.
                try:
                    result = redact_scan(scan, out, item.document, applied)
                except UnplacedSpan as exc:
                    if stats is not None:
                        stats.pdf(clean=False, boxes=0, scan=True)
                    raise HTTPException(
                        status_code=500,
                        detail="a withheld span could not be placed on the scan; not served",
                    ) from exc
            else:
                source = render_pdf(item.document, Path(tmp) / "source.pdf")
                result = apply_redactions(source, out, item.document, applied)
            checker = LeakChecker(use_ocr=False)
            checker.check(result.path, result.regions, document=doc_id, scan=scan is not None)
            clean = checker.report().clean
            if stats is not None:
                stats.pdf(clean=clean, boxes=len(result.regions), scan=scan is not None)
            if not clean:
                raise HTTPException(
                    status_code=500,
                    detail="the leak test found recoverable text under a box; not served",
                )
            body = result.path.read_bytes()
        return Response(
            content=body,
            media_type="application/pdf",
            headers={"content-disposition": f'attachment; filename="{doc_id}-released.pdf"'},
        )


def _cookie(scope: Scope, name: str) -> str | None:
    for header, value in scope.get("headers", ()):
        if header != b"cookie":
            continue
        raw: bytes = value
        for part in raw.decode("latin-1").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name and v:
                return v
    return None


async def _send(send: Send, status: int, body: bytes, content_type: str, cache: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"cache-control", cache.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _plain(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": body})
