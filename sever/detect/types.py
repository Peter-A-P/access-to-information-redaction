"""What a detector returns, and the interface any detector satisfies.

PLAN.md has detection coming from project 04's engine (`boundary.redact`, Presidio plus
custom recognisers). That module is 04 Part B and does not exist yet, so this package owns
a detector of its own built on the same stack. The protocol below is the seam: when 04
Part B lands, a `BoundaryDetector` implements `Detector` and nothing downstream changes.
The deviation and its reason are recorded in PLAN.md section 2.2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from sever.ingest.document import Document, Offsets


class EntityType(StrEnum):
    """The entity types the decision layer knows how to reason about.

    This is deliberately not Presidio's list. Presidio answers "what kind of string is
    this"; the decision layer needs "what kind of thing about a person is this", because
    the categories turn on it. A DATE is K6 almost always; a HEALTH_NUMBER is never
    anything but R1 or K1.
    """

    PERSON = "person"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    POSTAL_CODE = "postal_code"
    DATE = "date"
    DATE_OF_BIRTH = "date_of_birth"
    HEALTH_NUMBER = "health_number"
    SIN = "sin"
    FINANCIAL = "financial"
    FILE_NUMBER = "file_number"
    EMPLOYEE_ID = "employee_id"
    CASE_NUMBER = "case_number"
    ORGANISATION = "organisation"
    LOCATION = "location"
    JOB_TITLE = "job_title"
    URL = "url"
    IP_ADDRESS = "ip_address"
    OTHER = "other"

    @property
    def is_about_a_person(self) -> bool:
        """False for types that are never personal information on their own. A span of one
        of these types is a K6 candidate before any other rule runs, which is how the
        blunt baseline's over-redaction gets its shape."""
        return self not in (
            EntityType.ORGANISATION,
            EntityType.LOCATION,
            EntityType.DATE,
            EntityType.JOB_TITLE,
            EntityType.URL,
            EntityType.IP_ADDRESS,
        )

    @property
    def is_inherently_sensitive(self) -> bool:
        """Types where the mere fact of the value is personal information about someone,
        whatever their role. An official's health number is not about their position, so
        K2 must not reach it."""
        return self in (
            EntityType.HEALTH_NUMBER,
            EntityType.SIN,
            EntityType.DATE_OF_BIRTH,
            EntityType.FINANCIAL,
        )


@dataclass(frozen=True, slots=True)
class Detection:
    """One candidate span on one page.

    A detection is not a proposal. It says "there is something here"; sever.decide says
    what to do about it. Keeping the two apart is what makes the error decomposition
    possible: a leak is either a span the detector never saw or a span the decision layer
    got wrong, and the published table separates them.
    """

    page: int
    offsets: Offsets
    text: str
    entity_type: EntityType
    score: float
    recogniser: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0, 1], got {self.score}")
        if len(self.text) != len(self.offsets):
            raise ValueError(
                f"text {self.text!r} is {len(self.text)} characters but offsets span "
                f"{len(self.offsets)}; the detection and the page disagree"
            )

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.page, self.offsets.start, self.offsets.end)


@runtime_checkable
class Detector(Protocol):
    """Anything that finds candidate spans in a document."""

    name: str

    def detect(self, document: Document) -> Sequence[Detection]:
        """Every candidate span, in reading order: page, then start offset."""
        ...
