"""The append-only audit log.

Every reviewer action is a row: who, when, which page, which span, what they did and why.
Rows are never edited and never deleted. A reviewer who changes their mind adds a row that
supersedes an earlier one; the earlier one stays. That is what makes the log evidence
rather than a status field, and it is the difference between being able to answer "why was
this severed" a year later and not.

Append-only is enforced two ways, because a comment saying "do not update this table" is
not enforcement:

  1. This module exposes no update or delete method at all. There is no supported path to
     changing a row through the API, and a test asserts that no such method appears.
  2. Each row carries a hash chained to the previous row's hash, so a row that is changed,
     removed or reordered breaks the chain and `verify_chain` finds it and says which row.

There is deliberately no third way, and the reason is worth recording rather than leaving
as a gap. DuckDB has no triggers and no rule system, so the engine cannot refuse an UPDATE
against a table in a file somebody holds. An earlier version of this module issued
`CREATE RULE` statements and swallowed the parser error, which produced a `rules_enforced`
flag that was always false and read, to anyone skimming, like a guarantee. That is worse
than no defence, so it is gone. The hash chain is the guarantee, it does not depend on the
engine, and it is what makes this file evidence rather than a status table.
"""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

GENESIS = "0" * 64


class Action(StrEnum):
    """What a reviewer did. The closed set; the schedule is generated from APPROVE rows."""

    APPROVE = "approve"
    REJECT = "reject"
    ADD = "add"
    CHANGE_CATEGORY = "change_category"
    ESCALATE = "escalate"
    COMMENT = "comment"
    PAGE_COMPLETE = "page_complete"

    @property
    def withholds(self) -> bool:
        return self in (Action.APPROVE, Action.ADD, Action.ESCALATE)


class AuditImmutable(RuntimeError):
    """Raised on any attempt to change history."""


@dataclass(frozen=True, slots=True)
class AuditRow:
    seq: int
    at: dt.datetime
    actor: str
    request_id: str
    doc_id: str
    page: int
    action: Action
    span_start: int | None
    span_end: int | None
    span_text_sha256: str | None
    proposed_code: str | None
    final_code: str | None
    reason: str | None
    prev_hash: str
    row_hash: str

    def payload(self) -> str:
        """Exactly the bytes the hash covers. Sorted keys so it is reproducible."""
        return json.dumps(
            {
                "seq": self.seq,
                "at": self.at.isoformat(),
                "actor": self.actor,
                "request_id": self.request_id,
                "doc_id": self.doc_id,
                "page": self.page,
                "action": self.action.value,
                "span_start": self.span_start,
                "span_end": self.span_end,
                "span_text_sha256": self.span_text_sha256,
                "proposed_code": self.proposed_code,
                "final_code": self.final_code,
                "reason": self.reason,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def compute_hash(self) -> str:
        return hashlib.sha256(self.payload().encode("utf-8")).hexdigest()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq              BIGINT PRIMARY KEY,
    -- Named occurred_at rather than at: "at" is a reserved word in DuckDB and the
    -- table would not parse. The dataclass field stays `at`.
    occurred_at      TIMESTAMP NOT NULL,
    actor            VARCHAR NOT NULL,
    request_id       VARCHAR NOT NULL,
    doc_id           VARCHAR NOT NULL,
    page             INTEGER NOT NULL,
    action           VARCHAR NOT NULL,
    span_start       INTEGER,
    span_end         INTEGER,
    span_text_sha256 VARCHAR,
    proposed_code    VARCHAR,
    final_code       VARCHAR,
    reason           VARCHAR,
    prev_hash        VARCHAR NOT NULL,
    row_hash         VARCHAR NOT NULL
);
"""


@dataclass
class AuditLog:
    """An append-only log over one DuckDB file."""

    path: Path
    _con: duckdb.DuckDBPyConnection | None = None

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.path))
        self._con.execute(_SCHEMA)

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            raise RuntimeError("audit log is closed")
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def __enter__(self) -> AuditLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __len__(self) -> int:
        row = self.con.execute("SELECT count(*) FROM audit").fetchone()
        return int(row[0]) if row else 0

    def _head(self) -> tuple[int, str]:
        row = self.con.execute(
            "SELECT seq, row_hash FROM audit ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 0, GENESIS
        return int(row[0]), str(row[1])

    def append(
        self,
        *,
        request_id: str,
        doc_id: str,
        page: int,
        action: Action,
        actor: str | None = None,
        span_start: int | None = None,
        span_end: int | None = None,
        span_text: str | None = None,
        proposed_code: str | None = None,
        final_code: str | None = None,
        reason: str | None = None,
        at: dt.datetime | None = None,
    ) -> AuditRow:
        seq, prev = self._head()
        row = AuditRow(
            seq=seq + 1,
            at=at or dt.datetime.now(dt.UTC).replace(tzinfo=None),
            actor=actor or getpass.getuser(),
            request_id=request_id,
            doc_id=doc_id,
            page=page,
            action=action,
            span_start=span_start,
            span_end=span_end,
            span_text_sha256=(
                hashlib.sha256(span_text.encode("utf-8")).hexdigest() if span_text else None
            ),
            proposed_code=proposed_code,
            final_code=final_code,
            reason=reason,
            prev_hash=prev,
            row_hash="",
        )
        row = _with_hash(row)
        self.con.execute(
            "INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                row.seq, row.at, row.actor, row.request_id, row.doc_id, row.page,
                row.action.value, row.span_start, row.span_end, row.span_text_sha256,
                row.proposed_code, row.final_code, row.reason, row.prev_hash, row.row_hash,
            ],
        )
        return row

    def rows(self, *, request_id: str | None = None) -> tuple[AuditRow, ...]:
        sql = "SELECT * FROM audit"
        params: list[Any] = []
        if request_id is not None:
            sql += " WHERE request_id = ?"
            params.append(request_id)
        sql += " ORDER BY seq"
        return tuple(_row_from(r) for r in self.con.execute(sql, params).fetchall())

    def __iter__(self) -> Iterator[AuditRow]:
        return iter(self.rows())

    def verify_chain(self) -> tuple[bool, str]:
        """Recompute every hash. Returns (ok, message) naming the first broken row."""
        prev = GENESIS
        for row in self.rows():
            if row.prev_hash != prev:
                return False, (
                    f"row {row.seq} claims to follow {row.prev_hash[:12]} but the previous "
                    f"row hashes to {prev[:12]}; a row has been inserted, removed or reordered"
                )
            expected = row.compute_hash()
            if expected != row.row_hash:
                return False, (
                    f"row {row.seq} does not hash to its recorded value; its contents have "
                    f"been changed since it was written"
                )
            prev = row.row_hash
        return True, f"chain intact over {len(self)} rows"

    def approvals(self, request_id: str) -> tuple[AuditRow, ...]:
        """The rows the schedule is generated from: the latest action per span, kept only
        where that action withholds."""
        latest: dict[tuple[str, int, int | None, int | None], AuditRow] = {}
        for row in self.rows(request_id=request_id):
            if row.action is Action.PAGE_COMPLETE or row.action is Action.COMMENT:
                continue
            latest[(row.doc_id, row.page, row.span_start, row.span_end)] = row
        return tuple(
            sorted(
                (r for r in latest.values() if r.action.withholds),
                key=lambda r: (r.doc_id, r.page, r.span_start or 0),
            )
        )

    def pages_reviewed(self, request_id: str) -> frozenset[tuple[str, int]]:
        """Pages with an explicit completion action. No page is released without one."""
        return frozenset(
            (r.doc_id, r.page)
            for r in self.rows(request_id=request_id)
            if r.action is Action.PAGE_COMPLETE
        )


def _with_hash(row: AuditRow) -> AuditRow:
    digest = row.compute_hash()
    return AuditRow(**{**{f: getattr(row, f) for f in row.__slots__}, "row_hash": digest})


def _row_from(r: Sequence[Any]) -> AuditRow:
    return AuditRow(
        seq=int(r[0]),
        at=r[1],
        actor=str(r[2]),
        request_id=str(r[3]),
        doc_id=str(r[4]),
        page=int(r[5]),
        action=Action(r[6]),
        span_start=None if r[7] is None else int(r[7]),
        span_end=None if r[8] is None else int(r[8]),
        span_text_sha256=None if r[9] is None else str(r[9]),
        proposed_code=None if r[10] is None else str(r[10]),
        final_code=None if r[11] is None else str(r[11]),
        reason=None if r[12] is None else str(r[12]),
        prev_hash=str(r[13]),
        row_hash=str(r[14]),
    )
