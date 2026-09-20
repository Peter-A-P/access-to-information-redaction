"""What the privacy boundary costs in accuracy: the paired placeholders ablation.

PLAN.md section 1 promises this measurement and `docs/rejected.md` entry 2 leans on it.
The argument there is that over-masking costs the model context and therefore accuracy,
that under-masking costs a person their privacy, and that when one side of a trade shows up
in a results table and the other shows up in a breach the choice makes itself. That is a
good argument and it was, until now, missing its table.

The measurement is a paired run: the same spans, the same corpus, the same model, decided
twice. Once on typed placeholders, which is what the tool does. Once on the raw text, which
is what the tool refuses to do.

## Why this runs on a local model, and why that is not a compromise

The raw arm sends a payload containing names. This repository's rule is that no raw
detected entity leaves the boundary, `tests/test_no_raw_entity_leaves.py` asserts it across
the corpus, and `PlaceholderPolicy.guard` enforces it in the code path. A raw arm through a
hosted vendor would break all three, and the fact that the personas are invented does not
help: the property this project sells is that the pipeline *cannot* send a name, not that
the names it sends do not matter.

So the raw arm runs against a model on this machine, over loopback, and `assert_loopback`
refuses to build it against anything else. Three conditions, all checked before a single
request is constructed:

  * the provider is `price_zero`, so it is not a vendor;
  * it declares `residency: single-region`, which in 04's configuration only the local
    entry can honestly claim;
  * its base URL resolves to a loopback address.

Both arms run on that model, which is the part that makes this an ablation rather than two
runs. A placeholder arm on Haiku against a raw arm on a local 7B would measure the models,
not the boundary.

The honest cost of the design is that the number describes a small open-weights model
rather than the frontier model the pipeline uses in production, so it bounds the shape of
the effect and not its exact size on Haiku. That is written into the generated table rather
than left for a reader to infer. The compensating benefit is real: this ablation needs no
key, no vendor account and no spend, so unlike the rest of the model layer a stranger can
reproduce it by starting a local server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sever.context.record import ContextRecord
from sever.corpus.generate import Corpus, build
from sever.decide.model import GatewayModelDecider
from sever.decide.pipeline import DEFAULT_THRESHOLD, DecisionEngine
from sever.detect.engine import SeverDetector
from sever.detect.types import Detector
from sever.eval.confusion import Interval, Scored, score
from sever.eval.report import CachingDetector, config_for
from sever.taxonomy.loader import default_taxonomy

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

ABLATION_MAX_TOKENS = 120


class NotLoopback(RuntimeError):
    """The raw arm was pointed at something that is not a model on this machine."""


def assert_loopback(gateway: Any, model: str) -> None:
    """Refuse to build a raw-text decider against anything but a local model.

    Called before any raw payload exists, not before it is sent, because a payload that
    exists is a payload something can send.
    """
    provider_name = model.split("/", 1)[0] if "/" in model else ""
    providers = getattr(getattr(gateway, "config", None), "providers", {}) or {}
    provider = providers.get(provider_name)
    if provider is None:
        raise NotLoopback(
            f"the raw arm needs a provider this project can verify is local, and "
            f"{provider_name!r} is not in the gateway configuration. Use a model string "
            f"like 'local/qwen2.5:7b'."
        )
    host = (urlparse(getattr(provider, "base_url", "") or "").hostname or "").lower()
    failures: list[str] = []
    if not getattr(provider, "price_zero", False):
        failures.append("it is not declared price_zero, so it bills, so it is a vendor")
    if getattr(provider, "residency", None) != "single-region":
        failures.append("it does not declare residency: single-region")
    if host not in LOOPBACK_HOSTS:
        failures.append(f"its base URL host is {host!r}, which is not loopback")
    if failures:
        raise NotLoopback(
            "the raw arm of the placeholders ablation sends names, so it runs only against "
            f"a model on this machine. Provider {provider_name!r} was refused because "
            + "; ".join(failures)
            + ". Nothing was built and nothing was sent."
        )


def raw_context(ctx: ContextRecord) -> dict[str, object]:
    """`sever.decide.placeholders.redact_context`, with the redaction taken out.

    Field for field identical to what the real pipeline sends, so the only difference
    between the arms is whether the names are there. Anything else would measure the
    payload shape rather than the boundary.
    """
    return {
        "span": ctx.text,
        "entity_type": ctx.entity_type.value,
        "block": ctx.block_kind.value,
        "document_type": ctx.doc_type.value,
        "page": ctx.page_number,
        "pages_in_document": ctx.pages_in_document,
        "heading": ctx.heading,
        "sentence": ctx.sentence,
        "message_index": ctx.message_index,
        "is_configured_requester": ctx.is_requester,
        "requester_match_ambiguous": ctx.is_requester_ambiguous,
        "title_paired_with_this_person": ctx.title,
        "title_found_in": ctx.title_source,
        "mentioned_in": sorted({m.source for m in ctx.role_mentions}),
        "matches_public_register": ctx.register_match is not None,
        "appears_on_pages": list(ctx.cluster_pages),
        "distinct_surface_forms": len(ctx.cluster_surface_forms),
        "coreference_ambiguous": ctx.cluster_ambiguous,
        "other_people_in_same_sentence": len(ctx.co_mentions_in_sentence),
    }


@dataclass
class RawTextDecider(GatewayModelDecider):
    """The control arm. Sends the record as it is, names and all.

    A subclass rather than a flag on the real decider, so that nothing on the production
    path can reach this behaviour by passing an argument. Constructing one runs
    `assert_loopback`, and `build_request` does not call `policy.guard` because there is
    nothing for the guard to pass.
    """

    name: str = "raw-text-control"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.enabled:
            assert_loopback(self.gateway, self.model)

    def build_request(self, ctx: ContextRecord, policy: Any) -> tuple[str, dict[str, object]]:
        payload = raw_context(ctx)
        body = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True)
        message = f"Decide the category for this span.\n\n{body}\n\nReply with JSON only."
        return message, payload


@dataclass
class Arm:
    name: str
    note: str
    scored: Scored
    calls: int = 0

    @property
    def leak(self) -> Interval:
        return self.scored.leak_rate()

    @property
    def over(self) -> Interval:
        return self.scored.over_redaction_rate()

    @property
    def escalation(self) -> Interval:
        return self.scored.escalation_rate()


@dataclass
class Ablation:
    arms: list[Arm] = field(default_factory=list)
    documents: int = 0
    pages: int = 0
    model: str = ""
    agreement: float = 0.0
    compared: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"**Corpus:** {self.documents} documents, {self.pages} pages. "
            f"Model: `{self.model}`, on this machine over loopback, both arms.",
            "",
            "| Arm | Leak rate | Over-redaction | Escalation |",
            "|---|---|---|---|",
        ]
        for a in self.arms:
            lines.append(f"| {a.name} | {a.leak} | {a.over} | {a.escalation} |")
        lines += [
            "",
            f"The two arms gave the same category on **{self.agreement:.1%}** of the "
            f"{self.compared} spans both were asked about.",
            "",
            "Both arms run on the same local model because the raw arm sends names and "
            "this repository's rule is that names do not leave the machine; see the module "
            "docstring in `sever/eval/placeholders.py`. That makes the comparison exact and "
            "makes the size of the effect a statement about a small open-weights model "
            "rather than about the frontier model the pipeline uses. The shape of the "
            "effect is what this measures.",
        ]
        return "\n".join(lines)


def run(
    *,
    gateway: Any,
    model: str,
    documents: int = 60,
    seed: int = 20270802,
    detector: Detector | None = None,
    corpus: Corpus | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    cache_dir: Path | None = None,
) -> Ablation:
    """Decide the same corpus twice, on placeholders and on raw text."""
    assert_loopback(gateway, model)
    det = CachingDetector(inner=detector or SeverDetector())
    c = corpus or build(documents=documents, seed=seed)
    taxonomy = default_taxonomy()
    cache = cache_dir or Path(".cache/ablation")

    # The raw arm's replies can quote a name out of the payload, so its cache is written
    # under .cache/, which is gitignored, and never beside the committed one.
    # 120 rather than the pipeline's 400. The answer is one short JSON object, and on a
    # model running on a laptop's CPU the token budget is most of the wall clock. Both arms
    # get the same budget, which is what the comparison requires.
    masked = GatewayModelDecider(
        gateway=gateway,
        model=model,
        enabled=True,
        max_tokens=ABLATION_MAX_TOKENS,
        run_id="ablation-placeholders",
        cache_path=cache / "placeholders.jsonl",
    )
    raw = RawTextDecider(
        gateway=gateway,
        model=model,
        enabled=True,
        max_tokens=ABLATION_MAX_TOKENS,
        run_id="ablation-raw",
        cache_path=cache / "raw.jsonl",
    )

    pools: dict[str, dict[str, tuple[object, object]]] = {"masked": {}, "raw": {}}
    agreed = compared = 0
    for item in c:
        doc = item.rendered.document
        labels = item.rendered.labels
        config = config_for(item)
        by_arm = {}
        for key, decider in (("masked", masked), ("raw", raw)):
            proposals = DecisionEngine(
                config=config,
                detector=det,
                taxonomy=taxonomy,
                model=decider,
                model_confidence_threshold=threshold,
            ).propose(doc)
            pools[key][doc.doc_id] = (proposals, labels)
            by_arm[key] = {p.key: p.code for p in proposals if p.rule in ("model", "below_threshold")}
        shared = set(by_arm["masked"]) & set(by_arm["raw"])
        compared += len(shared)
        agreed += sum(1 for k in shared if by_arm["masked"][k] == by_arm["raw"][k])

    return Ablation(
        arms=[
            Arm(
                name="typed placeholders (what the tool does)",
                note="",
                scored=score(pools["masked"], taxonomy=taxonomy),  # type: ignore[arg-type]
                calls=masked.calls + masked.cache_reads,
            ),
            Arm(
                name="raw text (what the tool refuses to do)",
                note="",
                scored=score(pools["raw"], taxonomy=taxonomy),  # type: ignore[arg-type]
                calls=raw.calls + raw.cache_reads,
            ),
        ],
        documents=len(c),
        pages=c.page_count,
        model=model,
        agreement=agreed / compared if compared else 0.0,
        compared=compared,
    )


def write(result: Ablation, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- Generated by `sever eval-placeholders`. Do not hand-edit. -->\n\n"
        "# What the privacy boundary costs in accuracy\n\n"
        + result.to_markdown()
        + "\n",
        encoding="utf-8",
    )
    return path
