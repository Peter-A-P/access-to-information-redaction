"""Email messages about someone's own affairs, in which no one is released as an official.

An employee writing from their work address about their own leave, health, discipline or
grievance is a third party in that message, and so are their name, title and work
contacts. The rules could not see this. They released such an employee for the title in
their own signature block (`official_capacity`), their title as a bare role
(`not_personal_information`) and their work telephone as a business contact
(`official_capacity_contact`), and on the own-affairs trap set
(`sever/corpus/traps/own_affairs_email.tmpl`) the rules alone leaked 62.5 percent of what
had to be withheld.

So this module marks the messages, and the rules that release an official stand aside in
them. It does not decide that anyone in the message is a third party: the adviser
answering the email is doing their job, and telling the two apart is reading, which is
the model's work with the page in front of it. With the model off, the spans escalate and
are withheld, which is the repository's rule for what nobody has decided.

**What it reads.** A message runs from a `From:` email header to the next one. It is about
someone's own affairs when it says "my" or "your" before leave, health, a doctor, a
diagnosis, discipline, an accommodation, a grievance or a complaint. First and second
person only, because a case worker writing about "the client's health" or "their doctor"
is doing their job and is the ordinary case.

**What it does not claim.** The vocabulary was written beside one trap template, which
uses "my leave", "my doctor", "your leave" and "my grievance". A message that says "I am
off sick" without a possessive is missed, and its writer is released by the rules behind
this one. That is a leak the reviewer has to catch, and it is recorded in
docs/escalation.md.
"""

from __future__ import annotations

import re
from itertools import pairwise

from sever.ingest.document import BlockKind, Offsets, Page

_OWN_AFFAIRS = re.compile(
    r"\b(?:my|your)\s+(?:own\s+)?"
    r"(?:sick\s+|medical\s+|disability\s+|parental\s+|stress\s+)?"
    r"(?:leave|health|doctor|physician|diagnosis|illness|condition|medical"
    r"|disciplin\w*|accommodation|grievance|complaint|appeal)\b",
    re.IGNORECASE,
)
_FROM_LINE = re.compile(r"^\s*From:", re.IGNORECASE)


def is_own_affairs(text: str) -> bool:
    return bool(_OWN_AFFAIRS.search(text))


def own_affairs_messages(page: Page) -> tuple[Offsets, ...]:
    """The character ranges of the email messages on a page that are about the writer's
    or the recipient's own affairs."""
    starts = [
        b.offsets.start
        for b in page.blocks
        if b.kind is BlockKind.EMAIL_HEADER and _FROM_LINE.match(b.text)
    ]
    if not starts:
        return ()
    bounds = [*starts, len(page.text)]
    out: list[Offsets] = []
    for start, end in pairwise(bounds):
        if is_own_affairs(page.text[start:end]):
            out.append(Offsets(start, end))
    return tuple(out)
