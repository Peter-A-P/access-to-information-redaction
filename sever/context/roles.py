"""Reading capacity off the page: signature blocks, letterheads and email headers.

The single most useful fact about a name in a government record is usually not in the
sentence containing it. It is three inches lower, in the signature block, where the same
person appears with a title. This module finds those pairings, and the sentence-only
baseline in the evaluation exists precisely to measure how much they are worth.

Nothing here decides a category. It reports what the layout says, and sever.decide.rules
decides what that means.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sever.detect.recognisers import JOB_TITLE
from sever.ingest.document import Block, BlockKind, Document, Page

# "Marie Doucette" but not "Dear Sir" or "IN CONFIDENCE". Two to four capitalised words,
# allowing internal apostrophes, hyphens and lowercase particles.
_NAME_LINE = re.compile(
    r"^\s*((?:[A-Z][\w'\u2019-]+|d[eu]|van|von|de la|Mac|Mc)(?:\s+(?:[A-Z][\w'\u2019-]+|d[eu]|van|von|de|la))"
    r"{1,3})\s*[,.]?\s*$"
)
_EMAIL_HEADER_LINE = re.compile(
    r"^\s*(From|To|Cc|Bcc|Sent|Subject)\s*:\s*(.*)$", re.IGNORECASE
)
_NAME_WITH_EMAIL = re.compile(r"([^<>,;]+?)\s*<([^<>@\s]+@[^<>\s]+)>")
_NAME_COMMA_TITLE = re.compile(r"^\s*([A-Z][\w'\u2019-]+(?:\s+[A-Z][\w'\u2019-]+){1,3})\s*,\s*(.+?)\s*$")

_SALUTATIONS = frozenset({"dear", "sincerely", "regards", "yours", "thank", "attention"})


@dataclass(frozen=True, slots=True)
class RoleMention:
    """A name found somewhere that says what capacity it is named in."""

    name: str
    page: int
    block_kind: BlockKind
    title: str | None = None
    email: str | None = None
    # "signature", "letterhead", "email_from", "email_to", "attendee_list"
    source: str = "unknown"

    @property
    def is_capacity_bearing(self) -> bool:
        """True when the mention itself evidences an official capacity: a name with a
        title, or a name signing on letterhead."""
        return self.title is not None or self.source in ("letterhead", "signature")


def _looks_like_name(line: str) -> str | None:
    stripped = line.strip().rstrip(":;,")
    if not stripped or len(stripped) > 60:
        return None
    first = stripped.split()[0].casefold().rstrip(",")
    if first in _SALUTATIONS:
        return None
    m = _NAME_LINE.match(stripped)
    return m.group(1) if m else None


def _title_in(line: str) -> str | None:
    m = JOB_TITLE.pattern.search(line)
    return m.group(0) if m else None


def from_signature(block: Block, page: int) -> list[RoleMention]:
    """A signature block is a name, usually followed by a title, sometimes with contact
    details. The pairing is positional: the title is on the same line after a comma, or on
    the next line."""
    out: list[RoleMention] = []
    lines = block.text.splitlines()
    for i, line in enumerate(lines):
        inline = _NAME_COMMA_TITLE.match(line.strip())
        if inline and _title_in(inline.group(2)):
            out.append(
                RoleMention(
                    name=inline.group(1),
                    page=page,
                    block_kind=block.kind,
                    title=_title_in(inline.group(2)),
                    source="signature",
                )
            )
            continue
        name = _looks_like_name(line)
        if name is None:
            continue
        title = None
        for follow in lines[i + 1 : i + 3]:
            found = _title_in(follow)
            if found:
                title = found
                break
        out.append(
            RoleMention(
                name=name, page=page, block_kind=block.kind, title=title, source="signature"
            )
        )
    return out


def from_letterhead(block: Block, page: int) -> list[RoleMention]:
    out: list[RoleMention] = []
    lines = block.text.splitlines()
    for i, line in enumerate(lines):
        name = _looks_like_name(line)
        if name is None:
            continue
        title = _title_in(line)
        if title is None:
            for near in (lines[i - 1] if i else "", *lines[i + 1 : i + 2]):
                found = _title_in(near)
                if found:
                    title = found
                    break
        out.append(
            RoleMention(
                name=name, page=page, block_kind=block.kind, title=title, source="letterhead"
            )
        )
    return out


def from_email_header(block: Block, page: int) -> list[RoleMention]:
    """From/To/Cc lines. The From line is the author of that message in the chain, which
    matters because a quoted reply lower down has a different author and a signature
    inside a quote belongs to the quoted sender, not to the person who forwarded it."""
    out: list[RoleMention] = []
    for line in block.text.splitlines():
        m = _EMAIL_HEADER_LINE.match(line)
        if m is None:
            continue
        field_name, value = m.group(1).casefold(), m.group(2)
        if field_name not in ("from", "to", "cc", "bcc"):
            continue
        source = f"email_{field_name}"
        found_any = False
        for pair in _NAME_WITH_EMAIL.finditer(value):
            name = pair.group(1).strip(" ,;\"'")
            if _looks_like_name(name):
                out.append(
                    RoleMention(
                        name=name,
                        page=page,
                        block_kind=block.kind,
                        email=pair.group(2),
                        source=source,
                    )
                )
                found_any = True
        if not found_any:
            for chunk in re.split(r"[;,]", value):
                name = _looks_like_name(chunk)
                if name:
                    out.append(
                        RoleMention(
                            name=name, page=page, block_kind=block.kind, source=source
                        )
                    )
    return out


def from_attendee_list(block: Block, page: int) -> list[RoleMention]:
    """Minutes list attendees as "Name, Title" one per line. Treated as capacity-bearing
    only where a title is present: a bare name under "Present" could be a member of the
    public who attended."""
    out: list[RoleMention] = []
    for line in block.text.splitlines():
        m = _NAME_COMMA_TITLE.match(line.strip())
        if m is None:
            continue
        title = _title_in(m.group(2))
        if title is None:
            continue
        out.append(
            RoleMention(
                name=m.group(1),
                page=page,
                block_kind=block.kind,
                title=title,
                source="attendee_list",
            )
        )
    return out


def mentions_on(page: Page) -> list[RoleMention]:
    out: list[RoleMention] = []
    for block in page.blocks:
        if block.kind is BlockKind.SIGNATURE:
            out.extend(from_signature(block, page.number))
        elif block.kind in (BlockKind.LETTERHEAD, BlockKind.HEADER, BlockKind.FOOTER):
            out.extend(from_letterhead(block, page.number))
        elif block.kind is BlockKind.EMAIL_HEADER:
            out.extend(from_email_header(block, page.number))
        else:
            out.extend(from_attendee_list(block, page.number))
    return out


def mentions_in(document: Document) -> tuple[RoleMention, ...]:
    return tuple(m for page in document for m in mentions_on(page))


@dataclass(frozen=True, slots=True)
class RoleIndex:
    """Every capacity-bearing mention in a document, looked up by normalised name."""

    mentions: tuple[RoleMention, ...]

    @classmethod
    def build(cls, document: Document) -> RoleIndex:
        return cls(mentions=mentions_in(document))

    def _key(self, name: str) -> str:
        from sever.context.requester import normalise

        return normalise(name)

    def for_name(self, name: str) -> tuple[RoleMention, ...]:
        key = self._key(name)
        return tuple(m for m in self.mentions if self._key(m.name) == key)

    def title_for(self, name: str) -> str | None:
        for m in self.for_name(name):
            if m.title:
                return m.title
        return None

    def titled_names(self) -> frozenset[str]:
        return frozenset(m.name for m in self.mentions if m.title)

    def letterhead_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.mentions if m.source == "letterhead")

    def all_names(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for m in self.mentions:
            seen.setdefault(m.name, None)
        return tuple(seen)

    def sources_for(self, name: str) -> tuple[str, ...]:
        return tuple(m.source for m in self.for_name(name))


def names_from(mentions: Iterable[RoleMention]) -> Sequence[str]:
    return [m.name for m in mentions]
