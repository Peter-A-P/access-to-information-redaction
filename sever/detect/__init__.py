"""Candidate span detection: Presidio plus recognisers for access-to-information
identifiers. The Detector protocol is the seam for 04 Part B's engine."""

from sever.detect.engine import PresidioUnavailable, SeverDetector, default_detector
from sever.detect.types import Detection, Detector, EntityType

__all__ = [
    "Detection",
    "Detector",
    "EntityType",
    "PresidioUnavailable",
    "SeverDetector",
    "default_detector",
]
