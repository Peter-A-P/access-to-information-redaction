"""The demonstration's live counts: what visitors decided, across every visitor.

Read by the dashboard at `/dashboard` through `/dashboard.json`. The promise the demonstration
makes is that nothing a visitor does is kept, and this module keeps to it: it holds counts of
each kind of action and nothing else. No span text, no address, no cookie, no time finer than
the minute. The counts live in the process, and with `--stats-file` the running totals are
written to one small JSON file every half minute and when the server stops, and read back
when it starts, so an update to the site does not set the dashboard back to zero. The file
holds the same numbers `/dashboard.json` already publishes, and nothing else; the last hour's
per-minute activity is not kept, because after a restart it would describe a gap.

What is counted, and what is not:

  * **A person's decision** is a row a visitor's own action wrote: withhold, release,
    escalate, a change of category, or a selection the tool never proposed.
  * **A spread is not a decision.** When a person withholds a value and the screen withholds
    its other occurrences, those rows are counted separately, so the dashboard never credits
    the tool with an agreement a person did not make.
  * **Agreement** compares the person's outcome with the direction the tool proposed for the
    same span: withhold (an R code), release (a K code), or escalate (an E code, which has no
    direction to agree with and is shown by how people resolved it).
  * **Pages a public body released are counted apart.** On an invented record a visitor's
    agreement with the tool is agreement with labels the tool was built against; on a
    released page everything visible was already released by a person, so a visitor who
    withholds there is disagreeing with that person, not with the tool. Their decisions go
    into their own totals and agreement table, and the per-minute activity counts both.
"""

from __future__ import annotations

import atexit
import contextlib
import datetime as dt
import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sever.review.app.main import BULK_RELEASE_REASON
from sever.review.audit import Action
from sever.review.propagate import PROPAGATED_REASON

if TYPE_CHECKING:
    from sever.review.session import Item, RecordEvent, Session
    from sever.taxonomy.loader import Taxonomy

WINDOW_MINUTES = 60
OUTCOMES = ("withhold", "escalate", "release", "add")


def _direction(taxonomy: Taxonomy, code: str | None) -> str | None:
    if code is None:
        return None
    value = taxonomy.decision(code).value
    return {"redact": "withhold", "keep": "release", "escalate": "escalate"}.get(value)


@dataclass
class DemoStats:
    """Counts across every visitor. Thread-safe: the server answers requests on a pool."""

    taxonomy: Taxonomy
    tool: Mapping[str, int]
    tool_released: Mapping[str, int] = field(default_factory=dict)
    clock: Callable[[], float] = time.time
    since: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    visitors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _decisions: dict[str, int] = field(default_factory=lambda: dict.fromkeys(OUTCOMES, 0))
    _recategorised: int = 0
    _bulk: int = 0
    _spread: int = 0
    _pages: int = 0
    _records: int = 0
    _pdfs: dict[str, int] = field(
        default_factory=lambda: {"built": 0, "clean": 0, "refused": 0, "boxes": 0, "scans": 0}
    )
    _by_code: dict[str, dict[str, int]] = field(default_factory=dict)
    _agreement: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            k: {"decided": 0, "withhold": 0, "release": 0, "escalate": 0}
            for k in ("withhold", "release", "escalate")
        }
    )
    _minutes: deque[tuple[int, dict[str, int]]] = field(default_factory=deque)
    _released: dict[str, Any] = field(
        default_factory=lambda: {
            "decisions": dict.fromkeys(OUTCOMES, 0),
            "pages_completed": 0,
            "records_completed": 0,
            "spread": 0,
            "agreement": {
                k: {"decided": 0, "withhold": 0, "release": 0, "escalate": 0}
                for k in ("withhold", "release", "escalate")
            },
        }
    )

    # -- recording -----------------------------------------------------------------------

    def visitor(self) -> None:
        with self._lock:
            self.visitors += 1

    def _minute(self) -> dict[str, int]:
        now = int(self.clock() // 60)
        while self._minutes and self._minutes[0][0] <= now - WINDOW_MINUTES:
            self._minutes.popleft()
        if not self._minutes or self._minutes[-1][0] != now:
            self._minutes.append((now, dict.fromkeys(OUTCOMES, 0)))
        return self._minutes[-1][1]

    def observe(self, session: Session, event: RecordEvent) -> None:
        """One audit row a visitor's session just wrote."""
        if event.action is Action.COMMENT:
            return
        released = session.item(event.doc_id).released is not None
        with self._lock:
            if released:
                self._observe_released(session, event)
                return
            if event.action is Action.PAGE_COMPLETE:
                self._pages += 1
                if session.releasable(event.doc_id):
                    self._records += 1
                return
            if event.reason is not None and event.reason.startswith(PROPAGATED_REASON):
                self._spread += 1
                return
            outcome = self._outcome(event)
            if outcome is None:
                return
            if event.action is Action.ADD:
                self._decisions["add"] += 1
                self._minute()["add"] += 1
                return
            if event.action is Action.CHANGE_CATEGORY:
                self._recategorised += 1
            if event.reason == BULK_RELEASE_REASON:
                self._bulk += 1
            self._decisions[outcome] += 1
            self._minute()[outcome] += 1
            tool = _direction(self.taxonomy, event.proposed_code)
            if tool is None or event.proposed_code is None:
                return
            row = self._agreement[tool]
            row["decided"] += 1
            row[outcome] += 1
            code = self._by_code.setdefault(event.proposed_code, {"decided": 0, "agreed": 0})
            code["decided"] += 1
            agreed = outcome == tool or (tool == "withhold" and outcome == "escalate")
            code["agreed"] += int(agreed)

    def _observe_released(self, session: Session, event: RecordEvent) -> None:
        """The same reading as `observe`, into the released pages' own totals."""
        r = self._released
        if event.action is Action.PAGE_COMPLETE:
            r["pages_completed"] += 1
            if session.releasable(event.doc_id):
                r["records_completed"] += 1
            return
        if event.reason is not None and event.reason.startswith(PROPAGATED_REASON):
            r["spread"] += 1
            return
        outcome = self._outcome(event)
        if outcome is None:
            return
        if event.action is Action.ADD:
            outcome = "add"
        r["decisions"][outcome] += 1
        self._minute()[outcome] += 1
        tool = _direction(self.taxonomy, event.proposed_code)
        if outcome == "add" or tool is None:
            return
        row = r["agreement"][tool]
        row["decided"] += 1
        row[outcome] += 1

    def _outcome(self, event: RecordEvent) -> str | None:
        if event.action is Action.APPROVE or event.action is Action.ADD:
            return "withhold"
        if event.action is Action.REJECT:
            return "release"
        if event.action is Action.ESCALATE:
            return "escalate"
        if event.action is Action.CHANGE_CATEGORY:
            return _direction(self.taxonomy, event.final_code)
        return None

    def pdf(self, *, clean: bool, boxes: int, scan: bool = False) -> None:
        with self._lock:
            self._pdfs["built"] += 1
            self._pdfs["scans"] += int(scan)
            self._pdfs["clean" if clean else "refused"] += 1
            self._pdfs["boxes"] += boxes

    # -- reading -------------------------------------------------------------------------

    def snapshot(self, *, live: int) -> dict[str, Any]:
        with self._lock:
            self._minute()
            now = int(self.clock() // 60)
            filled = dict(self._minutes)
            minutes = [
                {
                    "t": dt.datetime.fromtimestamp(m * 60, dt.UTC).isoformat(),
                    **filled.get(m, dict.fromkeys(OUTCOMES, 0)),
                }
                for m in range(now - WINDOW_MINUTES + 1, now + 1)
            ]
            by_code = {
                code: {
                    "name": self.taxonomy[code].name,
                    "decided": v["decided"],
                    "agreed": v["agreed"],
                    "direction": _direction(self.taxonomy, code),
                }
                for code, v in sorted(self._by_code.items())
            }
            return {
                "since": self.since.isoformat(),
                "now": dt.datetime.now(dt.UTC).isoformat(),
                "visitors": self.visitors,
                "live": live,
                "decisions": dict(self._decisions),
                "decisions_total": sum(self._decisions.values()),
                "recategorised": self._recategorised,
                "bulk_released": self._bulk,
                "spread": self._spread,
                "pages_completed": self._pages,
                "records_completed": self._records,
                "pdfs": dict(self._pdfs),
                "agreement": {k: dict(v) for k, v in self._agreement.items()},
                "by_code": by_code,
                "minutes": minutes,
                "tool": dict(self.tool),
                "released": {
                    "decisions": dict(self._released["decisions"]),
                    "decisions_total": sum(self._released["decisions"].values()),
                    "pages_completed": self._released["pages_completed"],
                    "records_completed": self._released["records_completed"],
                    "spread": self._released["spread"],
                    "agreement": {k: dict(v) for k, v in self._released["agreement"].items()},
                    "tool": dict(self.tool_released),
                },
            }


    # -- keeping the totals across a restart ---------------------------------------------

    def state(self) -> dict[str, Any]:
        """The running totals, in the snapshot's own shape: what a restart must not lose."""
        snap = self.snapshot(live=0)
        released = {k: v for k, v in snap["released"].items() if k not in ("tool", "decisions_total")}
        kept = {k: v for k, v in snap.items() if k in _KEPT}
        kept["by_code"] = {
            c: {"decided": v["decided"], "agreed": v["agreed"]} for c, v in snap["by_code"].items()
        }
        return {**kept, "released": released}

    def restore(self, state: Mapping[str, Any]) -> None:
        """Add the totals a previous run saved to this one's. Reads `/dashboard.json` too."""

        def add(into: dict[str, int], saved: Mapping[str, Any]) -> None:
            for k, v in saved.items():
                if k in into:
                    into[k] += int(v)

        with self._lock:
            if state.get("since"):
                self.since = min(self.since, dt.datetime.fromisoformat(str(state["since"])))
            self.visitors += int(state.get("visitors", 0))
            add(self._decisions, state.get("decisions", {}))
            self._recategorised += int(state.get("recategorised", 0))
            self._bulk += int(state.get("bulk_released", 0))
            self._spread += int(state.get("spread", 0))
            self._pages += int(state.get("pages_completed", 0))
            self._records += int(state.get("records_completed", 0))
            add(self._pdfs, state.get("pdfs", {}))
            for k, row in state.get("agreement", {}).items():
                if k in self._agreement:
                    add(self._agreement[k], row)
            for code, row in state.get("by_code", {}).items():
                try:
                    self.taxonomy[code]
                except KeyError:
                    continue
                mine = self._by_code.setdefault(code, {"decided": 0, "agreed": 0})
                add(mine, row)
            r, saved = self._released, state.get("released", {})
            add(r["decisions"], saved.get("decisions", {}))
            for k in ("pages_completed", "records_completed", "spread"):
                r[k] += int(saved.get(k, 0))
            for k, row in saved.get("agreement", {}).items():
                if k in r["agreement"]:
                    add(r["agreement"][k], row)


_KEPT = (
    "since",
    "visitors",
    "decisions",
    "recategorised",
    "bulk_released",
    "spread",
    "pages_completed",
    "records_completed",
    "pdfs",
    "agreement",
)

SAVE_EVERY = 30.0


def save(stats: DemoStats, path: Path) -> None:
    """Write the totals beside the file and rename it over, so a crash mid-write leaves the
    previous file whole."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(stats.state(), sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def keep(stats: DemoStats, path: Path, *, every: float = SAVE_EVERY) -> threading.Event:
    """Read the totals `path` holds into `stats`, then save them every `every` seconds and
    when the process exits. Returns the event that stops the saving thread.

    An unreadable file is set aside as `<name>.unreadable` rather than overwritten, so a
    bad write never silently costs the history.
    """
    if path.is_file():
        try:
            stats.restore(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError, KeyError):
            path.replace(path.with_name(path.name + ".unreadable"))
    stop = threading.Event()

    def run() -> None:
        while not stop.wait(every):
            save(stats, path)

    threading.Thread(target=run, name="stats-keeper", daemon=True).start()
    def last() -> None:
        stop.set()
        # The folder can be gone by then, as a test's temporary directory is.
        with contextlib.suppress(OSError):
            save(stats, path)

    atexit.register(last)
    return stop


def tool_counts(items: Sequence[Item], taxonomy: Taxonomy) -> dict[str, int]:
    """What the engine proposed on the demonstration's records."""
    out = {"records": len(items), "spans": 0, "withhold": 0, "escalate": 0, "release": 0,
           "not_personal": 0}
    for item in items:
        for p in item.proposals:
            out["spans"] += 1
            if p.code == "K6":
                out["not_personal"] += 1
            elif p.is_escalation:
                out["escalate"] += 1
            elif p.withholds:
                out["withhold"] += 1
            else:
                out["release"] += 1
    return out


__all__ = ["OUTCOMES", "SAVE_EVERY", "WINDOW_MINUTES", "DemoStats", "keep", "save", "tool_counts"]
