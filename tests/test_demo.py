"""The public demonstration: visitors kept apart, nothing kept, and a real redacted PDF.

The demonstration reuses every screen and rule of the reviewer application, so what is
tested here is only what it adds: that two visitors never see each other's decisions, that
an evicted session leaves nothing on disk, that the gate still refuses an unreviewed record,
and that the PDF a visitor downloads has nothing under its boxes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from sever.review.demo import COOKIE, DemoServer, demo_items
from sever.review.session import Item


@pytest.fixture(scope="module")
def items() -> tuple[Item, ...]:
    return demo_items(documents=2)


@pytest.fixture()
def server(items: tuple[Item, ...]) -> Iterator[DemoServer]:
    s = DemoServer(items=items, secure_cookie=False)
    yield s
    s.max_sessions = 0
    s.visitor(None)  # evicts everything, including the one this creates


def test_a_new_visitor_gets_a_cookie_and_lands_where_they_asked(server: DemoServer) -> None:
    c = TestClient(server)
    r = c.get("/review", follow_redirects=False)
    assert r.status_code == 303 and COOKIE in r.headers["set-cookie"]
    assert r.headers["location"] == "/review"
    assert "HttpOnly" in r.headers["set-cookie"]
    assert "Every person in the invented records is invented" in c.get("/review").text


def test_two_visitors_never_see_each_other(server: DemoServer, items: tuple[Item, ...]) -> None:
    a, b = TestClient(server), TestClient(server)
    a.get("/review"), b.get("/review")
    doc = items[0].doc_id
    p = items[0].on_page(1)[0]
    a.post(
        f"/doc/{doc}/page/1/span",
        data={"start": p.detection.offsets.start, "end": p.detection.offsets.end, "action": "reject"},
    )
    assert "1 of" in a.get(f"/doc/{doc}/page/1").text
    assert "0 of" in b.get(f"/doc/{doc}/page/1").text
    assert len(server) == 2


def test_an_evicted_session_leaves_nothing_on_disk(items: tuple[Item, ...]) -> None:
    now = [0.0]
    s = DemoServer(items=items, idle=10, clock=lambda: now[0], secure_cookie=False)
    _, first, _ = s.visitor(None)
    folder = first.folder
    assert folder.exists()
    now[0] = 11.0
    s.visitor(None)
    assert not folder.exists()
    assert len(s) == 1


def test_the_pdf_is_refused_until_reviewed_and_then_has_nothing_under_its_boxes(
    server: DemoServer, items: tuple[Item, ...]
) -> None:
    c = TestClient(server)
    c.get("/review")
    item = items[0]
    doc = item.doc_id
    assert c.get(f"/doc/{doc}/released.pdf").status_code == 409
    withheld = []
    for p in item.on_page(1):
        action = "approve" if p.withholds else "reject"
        if p.withholds:
            withheld.append(p.detection.text)
        c.post(
            f"/doc/{doc}/page/1/span",
            data={"start": p.detection.offsets.start, "end": p.detection.offsets.end, "action": action},
        )
    c.post(f"/doc/{doc}/page/1/complete")
    r = c.get(f"/doc/{doc}/released.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = "".join(page.get_text() for page in pymupdf.open(stream=r.content, filetype="pdf"))
    long_names = [w for w in withheld if len(w) > 6]
    assert long_names and not any(w in text for w in long_names)


def test_health_needs_no_session(server: DemoServer) -> None:
    r = TestClient(server).get("/healthz", follow_redirects=False)
    assert r.status_code == 200 and len(server) == 0


# --- the website and the dashboard ----------------------------------------------------------


@pytest.fixture(scope="module")
def site(items: tuple[Item, ...], tmp_path_factory: pytest.TempPathFactory) -> Path:
    from sever.site import build

    out = tmp_path_factory.mktemp("site")
    build(out, items=items)
    return out


@pytest.fixture()
def with_site(items: tuple[Item, ...], site: Path) -> Iterator[DemoServer]:
    s = DemoServer(items=items, site=site, secure_cookie=False)
    yield s
    s.max_sessions = 0
    s.visitor(None)


@pytest.mark.parametrize("path", ["/", "/how", "/dashboard", "/style.css", "/app.js", "/data/site.json"])
def test_reading_about_it_needs_no_session(with_site: DemoServer, path: str) -> None:
    """Only the reviewer's screen gives a visitor a session; the site sets no cookie."""
    r = TestClient(with_site).get(path, follow_redirects=False)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers
    assert len(with_site) == 0


def test_a_file_the_site_does_not_have_is_a_404_not_a_session(with_site: DemoServer) -> None:
    r = TestClient(with_site).get("/fonts/nothing.woff2", follow_redirects=False)
    assert r.status_code == 404 and len(with_site) == 0


def test_the_dashboard_counts_decisions_and_never_their_text(
    with_site: DemoServer, items: tuple[Item, ...]
) -> None:
    c = TestClient(with_site)
    c.get("/review")
    item = items[0]
    p = next(p for p in item.on_page(1) if p.detection.text.strip())
    c.post(
        f"/doc/{item.doc_id}/page/1/span",
        data={"start": p.detection.offsets.start, "end": p.detection.offsets.end, "action": "reject"},
    )
    raw = TestClient(with_site).get("/dashboard.json")
    d = raw.json()
    assert d["visitors"] == 1 and d["live"] == 1
    assert d["decisions"]["release"] == 1 and d["decisions_total"] == 1
    assert sum(m["release"] for m in d["minutes"]) == 1
    assert p.detection.text not in raw.text
    assert item.doc_id not in raw.text


def test_a_spread_is_not_counted_as_a_persons_decision(
    with_site: DemoServer, items: tuple[Item, ...]
) -> None:
    from sever.review.propagate import occurrences

    c = TestClient(with_site)
    c.get("/review")
    for item in items:
        for p in item.on_page(1):
            if p.withholds and len(occurrences(item.document, p.detection.text)) > 1:
                c.post(
                    f"/doc/{item.doc_id}/page/1/span",
                    data={"start": p.detection.offsets.start, "end": p.detection.offsets.end, "action": "approve"},
                )
                d = TestClient(with_site).get("/dashboard.json").json()
                assert d["decisions_total"] == 1
                assert d["spread"] >= 1
                return
    pytest.skip("no repeated withheld value in these records")
