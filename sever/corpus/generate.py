"""Build the labelled corpus.

The offline path renders the templates directly and is what CI runs: deterministic from a
seed, free, and it produces the labels. PLAN.md section 2.4 additionally has a model
rewriting each rendered page into more natural prose through the gateway, which makes the
corpus harder and less template-shaped. That path costs money and is off by default; see
`sever.corpus.naturalise`. Everything downstream reads the same manifest either way, and
every published number says which corpus it came from.

One decision worth defending: the same six templates are rendered many times with
different casts rather than fifty templates being written. A template is a *structure*, and
what the decision layer has to get right is the interaction between structure and role, so
varying the cast across a fixed structure is the axis that matters. The risk is that the
corpus is too easy because the structures repeat, and that risk is exactly what the
published-federal-releases track exists to check.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sever.corpus import render as rnd
from sever.corpus.labels import LabelSet
from sever.corpus.personas import Persona, PersonaFactory, PersonaRole

DEFAULT_SEED = 20270802


@dataclass(frozen=True, slots=True)
class CorpusItem:
    doc_id: str
    template: str
    rendered: rnd.RenderedDocument

    @property
    def pages(self) -> int:
        return len(self.rendered.document)


@dataclass(frozen=True, slots=True)
class Corpus:
    items: tuple[CorpusItem, ...]
    seed: int
    split: Mapping[str, str]

    def __iter__(self) -> Iterator[CorpusItem]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def page_count(self) -> int:
        return sum(i.pages for i in self.items)

    def of_split(self, name: str) -> tuple[CorpusItem, ...]:
        return tuple(i for i in self.items if self.split[i.doc_id] == name)

    def label_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.items:
            for code, n in item.rendered.labels.by_code().items():
                out[code] = out.get(code, 0) + n
        return dict(sorted(out.items()))


def _cast_for(template: rnd.Template, factory: PersonaFactory) -> dict[str, Persona]:
    """Draw one persona per cast name, in the role the template asked for.

    Note that a name is drawn per document, not per corpus. Two documents can name
    different people in the same role, which is what makes the requester-match rule do
    real work: it has to find the configured requester rather than recognise a name it has
    seen before.
    """
    factory.begin_document()
    cast: dict[str, Persona] = {}
    for name, role_name in template.cast.items():
        try:
            role = PersonaRole(role_name)
        except ValueError as exc:
            raise rnd.TemplateError(
                f"{template.name}: cast entry {name}={role_name!r} is not a persona role "
                f"(one of {[r.value for r in PersonaRole]})"
            ) from exc
        cast[name] = factory.make(role)
    return cast


def build(
    *,
    documents: int = 60,
    seed: int = DEFAULT_SEED,
    template_dir: Path = rnd.TEMPLATE_DIR,
    splits: Sequence[tuple[str, float]] = (("train", 0.3), ("validation", 0.2), ("test", 0.5)),
) -> Corpus:
    """Render `documents` documents, cycling the templates so each is equally represented.

    The validation split exists because thresholds are set on it (PLAN.md 2.2). Setting a
    confidence threshold on the same pages the headline number is measured on would make
    the headline number a fit rather than a measurement.
    """
    templates = rnd.load_all(template_dir)
    if not templates:
        raise ValueError(f"no templates found in {template_dir}")
    factory = PersonaFactory(seed=seed)
    rng = random.Random(seed)

    items: list[CorpusItem] = []
    for i in range(documents):
        template = templates[i % len(templates)]
        doc_id = f"{template.doc_type.value}-{i:03d}"
        cast = _cast_for(template, factory)
        rendered = rnd.render(template, cast, doc_id=doc_id)
        problems = rnd.check_labels(rendered)
        if problems:
            raise AssertionError(
                "labels do not index the text they claim to:\n  " + "\n  ".join(problems)
            )
        items.append(CorpusItem(doc_id=doc_id, template=template.name, rendered=rendered))

    total = sum(w for _, w in splits)
    assignment: dict[str, str] = {}
    for item in items:
        draw = rng.random() * total
        acc = 0.0
        chosen = splits[-1][0]
        for name, weight in splits:
            acc += weight
            if draw <= acc:
                chosen = name
                break
        assignment[item.doc_id] = chosen
    return Corpus(items=tuple(items), seed=seed, split=assignment)


def write(corpus: Corpus, directory: Path) -> Path:
    """Write pages, labels and a manifest.

    Generated pages are gitignored; the manifest is not. That is the rule the whole
    portfolio follows: nothing raw is committed, and a published number is tied to its
    inputs by checksum rather than by trust.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pages").mkdir(exist_ok=True)
    (directory / "labels").mkdir(exist_ok=True)

    manifest: list[dict[str, object]] = []
    for item in corpus:
        doc = item.rendered.document
        payload = {
            "doc_id": doc.doc_id,
            "doc_type": doc.doc_type.value,
            "template": item.template,
            "pages": [
                {
                    "number": p.number,
                    "text": p.text,
                    "source": p.source.value,
                    "blocks": [
                        {
                            "kind": b.kind.value,
                            "start": b.offsets.start,
                            "end": b.offsets.end,
                        }
                        for b in p.blocks
                    ],
                }
                for p in doc
            ],
            "cast": {
                name: {"persona_id": p.persona_id, "role": p.role.value, "name": p.full_name}
                for name, p in item.rendered.cast.items()
            },
        }
        page_path = directory / "pages" / f"{doc.doc_id}.json"
        page_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        label_path = directory / "labels" / f"{doc.doc_id}.jsonl"
        item.rendered.labels.write(label_path)
        manifest.append(
            {
                "doc_id": doc.doc_id,
                "template": item.template,
                "doc_type": doc.doc_type.value,
                "split": corpus.split[doc.doc_id],
                "pages": item.pages,
                "labels": len(item.rendered.labels),
                "by_code": item.rendered.labels.by_code(),
                "pages_sha256": _sha256_text(page_path.read_text(encoding="utf-8")),
                "labels_sha256": _sha256_text(label_path.read_text(encoding="utf-8")),
            }
        )

    manifest_path = directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "seed": corpus.seed,
                "documents": len(corpus),
                "pages": corpus.page_count,
                "by_code": corpus.label_counts(),
                "splits": {
                    name: sum(1 for v in corpus.split.values() if v == name)
                    for name in sorted(set(corpus.split.values()))
                },
                "items": manifest,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest_path


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_labels(directory: Path) -> dict[str, LabelSet]:
    return {
        p.stem: LabelSet.read(p) for p in sorted((directory / "labels").glob("*.jsonl"))
    }
