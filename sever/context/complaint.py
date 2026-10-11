"""The parties to a confidential workplace complaint.

Reviewer 1's ruling, 2026-10-10, after the first real study run: the complainant and the
respondent in an internal, confidential complaint are third parties, and so are their job
titles. The exclusion for officials covers information about an employee's position or
functions, and a complaint against someone, or by someone, is about them as a person, not
about the position. It has nothing to do with the requester. And the title cannot be
released with the name withheld, because in a division with one Regional Director the
title is the name.

So this module answers two questions about a document: is it a confidential workplace
complaint, and which people are its parties. Nothing here decides a category; the
`complaint_party` rule does, ahead of the rules that would release an official.

**What it reads.** A record that is marked confidential and is about a workplace complaint
(respectful workplace, harassment, grievance, a workplace investigation). Then every
sentence that names a party role ("the complainant", "the respondent", "the complaint was
made by", "the complaint names"): the people in it are parties, and so is everything
else in their coreference cluster, so a later "Fiona responded in writing" is a party
too. A job title in such a sentence is a party's title.

**What it does not claim.** One template in the corpus exercises this (the HR
memorandum), so the measured effect is on the phrasing that template uses. A real
complaint file phrases its parties many ways; a party this misses goes to the rules
behind it, which release a titled official, so the misses are leaks and the reviewer is
the backstop. That is recorded in docs/escalation.md.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sever.ingest.document import Document

_CONFIDENTIAL = re.compile(r"\bin confidence\b|\bconfidential\b", re.IGNORECASE)
_WORKPLACE_COMPLAINT = re.compile(
    r"\brespectful workplace\b|\bharassment\b|\bgrievances?\b|\bworkplace (?:complaint|investigation)\b",
    re.IGNORECASE,
)
_PARTY_SENTENCE = re.compile(
    r"\b(?:complainant|respondent|grievor|grievant)\b"
    r"|\bcomplaint (?:was|is|has been) (?:made|filed|brought|lodged) by\b"
    r"|\bcomplaint names\b",
    re.IGNORECASE,
)


def is_confidential_complaint(document: Document) -> bool:
    text = "\n".join(page.text for page in document)
    return bool(_CONFIDENTIAL.search(text)) and bool(_WORKPLACE_COMPLAINT.search(text))


def is_party_sentence(sentence: str) -> bool:
    return bool(_PARTY_SENTENCE.search(sentence))


@dataclass(frozen=True, slots=True)
class ComplaintParties:
    """The coreference clusters of the people a complaint is about."""

    clusters: frozenset[str]

    @classmethod
    def find(
        cls, document: Document, sentences_and_clusters: Sequence[tuple[str, str | None]]
    ) -> ComplaintParties:
        """`sentences_and_clusters` is (sentence, cluster id) for each person detected."""
        if not is_confidential_complaint(document):
            return cls(clusters=frozenset())
        return cls(
            clusters=frozenset(
                cluster
                for sentence, cluster in sentences_and_clusters
                if cluster is not None and is_party_sentence(sentence)
            )
        )
