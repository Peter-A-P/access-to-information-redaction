"""Recovering a page's structure from its text: signature blocks, letterheads, email headers.

A scan and a released PDF arrive as lines of text with nothing saying which lines were a
signature block. Until 2026-10-17 both were read as paragraphs of BODY, and the cost of
that was measured twice: twenty points of over-redaction on the scanned track, where the
truth is known, and every one of 533 spans withheld on the real-record track. The rules
lean hardest on exactly what was lost. A name in a signature block with a title under it
is an official signing a letter; the same name in a paragraph is just a name.

## What it reads, and what it does not

The text, line by line: where the blank lines fall, how long each line is, and what the
lines say. "Sincerely," followed by short lines is a signature block. A name on its own
line with a title or a rank on the next is one too, which is how a signature is laid out
whether or not anybody wrote "Sincerely" above it. "From:", "Sent:" and "Subject:" lines
are an email header, including the form OCR produces from a printed Outlook message, where
each label sits on a line of its own and the value on the next. A short first paragraph
that opens with the name of a public body is a letterhead.

It does not read the geometry. Tesseract and PyMuPDF both return word positions, and a
signature block's indentation or a letterhead's place at the top of the page would add
evidence. Text alone was tried first because it works the same on all three inputs (a
native render, an OCR read-back, and the text layer of a released PDF), and because what
it recovers is measurable against the native blocks on the synthetic corpus, which is the
check in `results/layout.md`. Geometry is the next step if that check says text is not
enough.

## Which way it errs

Toward BODY. A block this module cannot place is a paragraph, which is what every block
was before it existed, so the worst it can do on a page it does not understand is nothing.
The one direction that would cost a requester is a name wrongly put in a signature block,
which releases it as an official's; the rules for a signature require a name on a line of
its own with a title or rank within two lines, or a closing word above it, and the letterhead
rule requires the first paragraph to open with the name of a public body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sever.context.roles import _looks_like_name, _title_in
from sever.ingest.document import Block, BlockKind, Offsets

# A line this long is prose. Signature, letterhead and header lines are short.
SHORT_LINE = 70
# The most lines a signature block runs to: name, title, unit, two numbers, an address.
SIGNATURE_LINES = 7

_CLOSING = re.compile(
    r"^(?:sincerely|yours (?:truly|sincerely|faithfully)|respectfully(?: yours)?|"
    r"(?:best |kind |warm(?:est)? )?regards|best wishes|cheers|thanks|thank you|merci|"
    r"cordialement|salutations distinguées)[,.!]?$",
    re.IGNORECASE,
)
# Who took and who approved a set of minutes, written at the foot as a signature is.
_SIGNED_LINE = re.compile(r"^(?:minutes taken by|approved by)\s", re.I)
# "Ce" and "Cec" are "Cc" as OCR reads it off a printed header.
_HEADER_LABEL = re.compile(r"^(From|To|Cc|Ce|Cec|Bcc|Sent|Subject|Date)\s*:\s*(.*)$", re.I)
_SALUTATION = re.compile(
    r"^(?:dear|hello|hi|good (?:morning|afternoon)|sir|madam|monsieur|madame|bonjour)\b"
    r".{0,50}[,:]$",
    re.IGNORECASE,
)
_ATTACHMENT = re.compile(r"^(?:encl\.?|enclosures?\b|attachments?\s*:|c\.c\.|cc\s*:)", re.I)
# The first line of a letterhead names the body, and the body's name has one of these
# words in it. The first line and not any line: "John Smith / Smith Services Ltd" at the
# top of a page is a correspondent, and a name in a letterhead is read as published.
_PUBLIC_BODY = re.compile(
    r"\b(?:Department|Office|Ministry|Government|Province|Town|City|Services|Authority|"
    r"Commission|Agency|Board|Council|Secretariat|Defence|Ministère|Cabinet|Gouvernement|"
    r"Défense|Ministre)\b"
)
_LETTERHEAD_LINES = 6
_HEADING_CHARS = 60


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    end: int
    text: str

    @property
    def stripped(self) -> str:
        return self.text.strip()

    @property
    def blank(self) -> bool:
        return not self.stripped

    @property
    def short(self) -> bool:
        return len(self.stripped) <= SHORT_LINE


def _lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    position = 0
    for raw in text.split("\n"):
        out.append(_Line(position, position + len(raw), raw))
        position += len(raw) + 1
    return out


def _email_header_runs(lines: list[_Line], kinds: list[BlockKind | None]) -> None:
    """Mark runs of From/Sent/To/Subject lines. A memorandum has From, To, Date and Subject
    too, and its header is body text in the corpus, so a run counts as an email header only
    with a Sent line or an address in it."""
    i = 0
    while i < len(lines):
        if _HEADER_LABEL.match(lines[i].stripped) is None:
            i += 1
            continue
        run: list[int] = []
        labels: set[str] = set()
        j = i
        while j < len(lines):
            m = _HEADER_LABEL.match(lines[j].stripped)
            if m is None:
                break
            labels.add(m.group(1).casefold())
            run.append(j)
            j += 1
            # The label alone on its line, the value on the next.
            if (
                not m.group(2).strip()
                and j < len(lines)
                and not lines[j].blank
                and _HEADER_LABEL.match(lines[j].stripped) is None
            ):
                run.append(j)
                j += 1
        text = " ".join(lines[k].stripped for k in run)
        if len(labels) >= 2 and ("sent" in labels or "@" in text):
            for k in run:
                kinds[k] = BlockKind.EMAIL_HEADER
        i = max(j, i + 1)


def _signature_from(lines: list[_Line], kinds: list[BlockKind | None], at: int) -> int:
    """Mark a signature block starting at `at`; return the index after it."""
    j = at
    taken = 0
    while j < len(lines) and taken < SIGNATURE_LINES:
        line = lines[j]
        if line.blank or not line.short or kinds[j] is not None:
            break
        if _HEADER_LABEL.match(line.stripped):
            break
        kinds[j] = BlockKind.SIGNATURE
        taken += 1
        j += 1
    return j


def _signatures(lines: list[_Line], kinds: list[BlockKind | None]) -> None:
    i = 0
    while i < len(lines):
        if kinds[i] is not None or lines[i].blank:
            i += 1
            continue
        text = lines[i].stripped
        if _CLOSING.match(text):
            kinds[i] = BlockKind.SIGNATURE
            j = i + 1
            # "Sincerely," then a blank line or two for the signature itself.
            while j < len(lines) and j <= i + 3 and lines[j].blank:
                j += 1
            if j < len(lines) and _looks_like_name(lines[j].stripped):
                i = _signature_from(lines, kinds, j)
                continue
            i += 1
            continue
        if _SIGNED_LINE.match(text) and lines[i].short:
            j = i
            while j < len(lines) and _SIGNED_LINE.match(lines[j].stripped) and kinds[j] is None:
                kinds[j] = BlockKind.SIGNATURE
                j += 1
            i = j
            continue
        if lines[i].short and _looks_like_name(text):
            following = [
                k for k in range(i + 1, min(i + 3, len(lines))) if not lines[k].blank
            ]
            if any(lines[k].short and _title_in(lines[k].stripped) for k in following):
                i = _signature_from(lines, kinds, i)
                continue
        i += 1


def _paragraphs(lines: list[_Line]) -> list[list[int]]:
    out: list[list[int]] = []
    current: list[int] = []
    for k, line in enumerate(lines):
        if line.blank:
            if current:
                out.append(current)
                current = []
        else:
            current.append(k)
    if current:
        out.append(current)
    return out


def _per_paragraph(lines: list[_Line], kinds: list[BlockKind | None]) -> None:
    paragraphs = _paragraphs(lines)
    for n, para in enumerate(paragraphs):
        free = [k for k in para if kinds[k] is None]
        if not free:
            continue
        first = lines[para[0]].stripped
        if (
            n == 0
            and len(para) <= _LETTERHEAD_LINES
            and all(lines[k].short for k in para)
            and _PUBLIC_BODY.search(first)
            and _looks_like_name(first) is None
            and len(free) == len(para)
        ):
            for k in para:
                kinds[k] = BlockKind.LETTERHEAD
            continue
        if len(para) == 1 and len(free) == 1:
            text = first
            if _SALUTATION.match(text):
                kinds[para[0]] = BlockKind.SALUTATION
                continue
            if (
                len(text) <= _HEADING_CHARS
                and ":" not in text
                and text[-1] not in ".,;:"
                and _looks_like_name(text) is None
            ):
                kinds[para[0]] = BlockKind.HEADING
                continue
        if _ATTACHMENT.match(lines[free[0]].stripped):
            for k in free:
                kinds[k] = BlockKind.ATTACHMENT_NOTE


def classify_lines(text: str) -> list[tuple[_Line, BlockKind]]:
    """Every non-blank line with the kind of block it belongs to."""
    lines = _lines(text)
    kinds: list[BlockKind | None] = [None] * len(lines)
    _email_header_runs(lines, kinds)
    _signatures(lines, kinds)
    _per_paragraph(lines, kinds)
    return [
        (line, kind if kind is not None else BlockKind.BODY)
        for line, kind in zip(lines, kinds, strict=True)
        if not line.blank
    ]


def recover_blocks(text: str) -> tuple[Block, ...]:
    """The page's blocks, each with the kind its lines were given.

    A block is a run of lines of one kind with no blank line inside it, except that a
    signature keeps the blank line between "Sincerely," and the name, as the native render
    does. Offsets are trimmed to the text so that `Block.text` is the slice it claims.
    """
    blocks: list[Block] = []
    current: list[_Line] = []
    current_kind: BlockKind | None = None
    previous_end = -1

    def flush() -> None:
        if not current or current_kind is None:
            return
        start = current[0].start + (len(current[0].text) - len(current[0].text.lstrip()))
        end = current[-1].start + len(current[-1].text.rstrip())
        blocks.append(
            Block(kind=current_kind, offsets=Offsets(start, end), text=text[start:end])
        )

    for line, kind in classify_lines(text):
        # A blank line between this line and the last one ends a paragraph.
        broke = previous_end >= 0 and line.start > previous_end + 1
        joined = bool(current) and kind is current_kind and (
            not broke or kind is BlockKind.SIGNATURE
        )
        if not joined:
            flush()
            current = []
            current_kind = kind
        current.append(line)
        previous_end = line.end
    flush()
    return tuple(blocks)


__all__ = ["SHORT_LINE", "classify_lines", "recover_blocks"]
