"""Within-document coreference over person mentions.

Not a general coreference resolver. It answers one question: which mentions in this record
are the same person? "Marie Doucette" in the letterhead, "Ms Doucette" in paragraph two
and "Marie" in paragraph five are one person, and once one of them is placed as an
official the other two follow.

This matters more than its size suggests. Without it, the decision layer treats every
mention independently and produces the inconsistency that PLAN.md predicts of the
model-only baseline: the same person kept on page one and redacted on page three, in the
same released record. A reviewer notices that immediately and stops trusting the tool.

The rule is conservative. Mentions link when one name's parts are a subset of the other's
and no third person in the document competes for the shared part. A forename shared by
two people links to neither.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sever.context.requester import normalise
from sever.detect.recognisers import RANK_SHORT_FORMS
from sever.detect.types import Detection, EntityType


@dataclass(frozen=True, slots=True)
class Cluster:
    cluster_id: str
    # The longest surface form seen, which is the one most likely to be the full name.
    canonical: str
    mentions: tuple[Detection, ...]
    # Set when a mention was linked only on a shared name part and something else in the
    # document could own that part. An ambiguous cluster is a reason to escalate, not to
    # guess, so it is carried rather than dropped.
    ambiguous: bool = False

    @property
    def surface_forms(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for m in self.mentions:
            seen.setdefault(m.text, None)
        return tuple(seen)

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(sorted({m.page for m in self.mentions}))


@dataclass(frozen=True, slots=True)
class CorefIndex:
    clusters: tuple[Cluster, ...]
    _by_key: dict[tuple[int, int, int], Cluster] = field(default_factory=dict)

    def cluster_for(self, detection: Detection) -> Cluster | None:
        return self._by_key.get(detection.key)

    def cluster(self, cluster_id: str) -> Cluster | None:
        for c in self.clusters:
            if c.cluster_id == cluster_id:
                return c
        return None

    def __len__(self) -> int:
        return len(self.clusters)


def _parts(name: str) -> frozenset[str]:
    return frozenset(
        p
        for p in normalise(name).split()
        if len(p) > 1 and p not in _HONORIFICS and p not in _RANKS
    )


_HONORIFICS = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "prof", "hon", "sir", "madam", "rev", "mx"}
)

# Military ranks in their short forms, for the same reason as an honorific: "McGuffin LCol"
# and "Chris McGuffin" are one person, and with "lcol" counted as a name part the bare
# "McGuffin" belonged to both and its cluster was marked ambiguous. The full words are left
# out because Major and Sargent are surnames.
_RANKS = frozenset(normalise(r) for r in RANK_SHORT_FORMS)


def build(
    detections: Sequence[Detection], *, extra_names: Iterable[str] = ()
) -> CorefIndex:
    """Cluster the PERSON detections. `extra_names` are names known from the layout that
    the detector may not have flagged (a signature-block name it missed); they take part
    in the ambiguity check without becoming mentions of their own."""
    people = [d for d in detections if d.entity_type is EntityType.PERSON]
    known = [(_parts(d.text), d) for d in people if _parts(d.text)]
    extra = [_parts(n) for n in extra_names if _parts(n)]

    # Longest names first: a full name seeds a cluster and shorter forms attach to it.
    order = sorted(known, key=lambda pair: (-len(pair[0]), -len(pair[1].text)))

    seeds: list[tuple[frozenset[str], list[Detection], bool]] = []
    for parts, det in order:
        candidates = [i for i, (sp, _, _) in enumerate(seeds) if parts <= sp or sp <= parts]
        if not candidates:
            seeds.append((parts, [det], False))
            continue
        if len(candidates) > 1:
            # More than one existing person could own this mention. Attach it to the
            # first and mark the cluster ambiguous so the rules escalate rather than
            # inheriting a role from a coin flip.
            idx = candidates[0]
            sp, members, _ = seeds[idx]
            seeds[idx] = (sp | parts, [*members, det], True)
            continue
        idx = candidates[0]
        sp, members, amb = seeds[idx]
        # A partial form is ambiguous if a name outside the detections also owns the part.
        competing = sum(1 for e in extra if parts <= e and not (e <= sp or sp <= e))
        seeds[idx] = (sp | parts, [*members, det], amb or competing > 0)

    clusters: list[Cluster] = []
    by_key: dict[tuple[int, int, int], Cluster] = {}
    for i, (_, members, ambiguous) in enumerate(seeds):
        ordered = tuple(sorted(members, key=lambda d: (d.page, d.offsets.start)))
        canonical = max((m.text for m in ordered), key=len)
        cluster = Cluster(
            cluster_id=f"c{i:03d}",
            canonical=canonical,
            mentions=ordered,
            ambiguous=ambiguous,
        )
        clusters.append(cluster)
        for m in ordered:
            by_key[m.key] = cluster
    return CorefIndex(clusters=tuple(clusters), _by_key=by_key)
