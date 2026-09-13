"""Render a template into a page of text and the exact labels for every span in it.

The template format is deliberately small. A file is a sequence of blocks; a block starts
with a directive line and runs to the next one:

    @doc correspondence
    @cast requester=requester official=official third_party=third_party
    @block letterhead
    {official.organisation}
    @block signature
    Sincerely,
    {official.full_name}
    {official.title}

Inside a block, `{role.field}` inserts a persona's field and records a label for exactly
the characters it inserted. `{role.field!CODE}` overrides the category for that one
occurrence, which is how a trap is written: an official who appears as the complainant in
their own grievance is `{official_a.full_name!R1}`, correctly labelled R1 even though the
persona is an official.

`{{` and `}}` are literal braces. `@page` starts a new page. `@literal` marks a block whose
braces are not substituted at all.

Why a bespoke format rather than Jinja: the renderer has to know the character offset of
every substitution in the finished text, and a general template engine gives back a string
with that information thrown away. Recovering offsets afterwards by searching for the
inserted value is where corpora acquire silent label errors, because a name that occurs
twice matches in the wrong place.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from sever.corpus.labels import LabelledSpan, LabelSet, LabelSource
from sever.corpus.personas import Persona
from sever.ingest.document import (
    Block,
    BlockKind,
    Document,
    DocumentMetadata,
    DocumentType,
    Offsets,
    Page,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)(?:!([A-Z]\d))?\}")
_DIRECTIVE = re.compile(r"^@(doc|cast|block|page|literal|meta)\b\s*(.*)$")


class TemplateError(ValueError):
    """A template that cannot be rendered. Always names the file and the line."""


@dataclass(frozen=True, slots=True)
class TemplateBlock:
    kind: BlockKind
    body: str
    page: int
    literal: bool = False


@dataclass(frozen=True, slots=True)
class Template:
    name: str
    doc_type: DocumentType
    cast: Mapping[str, str]
    blocks: tuple[TemplateBlock, ...]
    meta: Mapping[str, str] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return max((b.page for b in self.blocks), default=1)

    @property
    def roles_used(self) -> frozenset[str]:
        names: set[str] = set()
        for b in self.blocks:
            if b.literal:
                continue
            names.update(m.group(1) for m in _PLACEHOLDER.finditer(b.body))
        return frozenset(names)


def parse(text: str, *, name: str = "<string>") -> Template:
    doc_type = DocumentType.OTHER
    cast: dict[str, str] = {}
    meta: dict[str, str] = {}
    blocks: list[TemplateBlock] = []
    kind: BlockKind | None = None
    literal = False
    page = 1
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if kind is not None and buf:
            body = "\n".join(buf).strip("\n")
            if body.strip():
                blocks.append(TemplateBlock(kind=kind, body=body, page=page, literal=literal))
        buf = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _DIRECTIVE.match(line)
        if m is None:
            buf.append(line)
            continue
        directive, rest = m.group(1), m.group(2).strip()
        if directive == "doc":
            flush()
            try:
                doc_type = DocumentType(rest)
            except ValueError as exc:
                raise TemplateError(f"{name}:{lineno}: unknown document type {rest!r}") from exc
        elif directive == "cast":
            flush()
            for pair in rest.split():
                if "=" not in pair:
                    raise TemplateError(
                        f"{name}:{lineno}: cast entries are name=role, got {pair!r}"
                    )
                key, role = pair.split("=", 1)
                cast[key] = role
        elif directive == "meta":
            flush()
            if ":" not in rest:
                raise TemplateError(f"{name}:{lineno}: meta entries are key: value")
            key, value = rest.split(":", 1)
            meta[key.strip()] = value.strip()
        elif directive == "page":
            flush()
            page += 1
            kind = None
        elif directive in ("block", "literal"):
            flush()
            literal = directive == "literal"
            wanted = rest or "body"
            try:
                kind = BlockKind(wanted)
            except ValueError as exc:
                raise TemplateError(f"{name}:{lineno}: unknown block kind {wanted!r}") from exc
    flush()
    if not blocks:
        raise TemplateError(f"{name}: template has no blocks")
    if not cast:
        raise TemplateError(f"{name}: template declares no cast")
    return Template(name=name, doc_type=doc_type, cast=cast, blocks=tuple(blocks), meta=meta)


def load(path: Path) -> Template:
    return parse(path.read_text(encoding="utf-8"), name=path.name)


def load_all(directory: Path = TEMPLATE_DIR) -> tuple[Template, ...]:
    return tuple(load(p) for p in sorted(directory.glob("*.tmpl")))


@dataclass
class _PageBuilder:
    """Accumulates one page's text, blocks and labels, tracking offsets as it goes."""

    number: int
    parts: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    labels: list[LabelledSpan] = field(default_factory=list)
    length: int = 0

    def add_block(self, kind: BlockKind, rendered: str, spans: list[tuple[int, int, str, str, str]]) -> None:
        if self.parts:
            self.parts.append("\n\n")
            self.length += 2
        start = self.length
        self.parts.append(rendered)
        self.length += len(rendered)
        self.blocks.append(
            Block(kind=kind, offsets=Offsets(start, self.length), text=rendered)
        )
        for rel_start, rel_end, text, code, meta in spans:
            persona_id, field_name = meta.split("|", 1)
            self.labels.append(
                LabelledSpan(
                    page=self.number,
                    offsets=Offsets(start + rel_start, start + rel_end),
                    text=text,
                    code=code,
                    persona_id=persona_id or None,
                    field_name=field_name or None,
                )
            )

    def build(self) -> Page:
        return Page(number=self.number, text="".join(self.parts), blocks=tuple(self.blocks))


def _render_block(
    body: str, personas: Mapping[str, Persona], *, where: str
) -> tuple[str, list[tuple[int, int, str, str, str]]]:
    """Substitute placeholders, returning the text and (start, end, text, code, meta)."""
    out: list[str] = []
    spans: list[tuple[int, int, str, str, str]] = []
    cursor = 0
    pos = 0
    while True:
        m = _PLACEHOLDER.search(body, pos)
        if m is None:
            break
        literal_before = body[pos : m.start()].replace("{{", "{").replace("}}", "}")
        out.append(literal_before)
        cursor += len(literal_before)

        role, field_name, override = m.group(1), m.group(2), m.group(3)
        persona = personas.get(role)
        if persona is None:
            raise TemplateError(
                f"{where}: template uses role {role!r}, which the cast does not provide "
                f"(cast has {sorted(personas)})"
            )
        try:
            value = persona.get(field_name)
        except KeyError as exc:
            raise TemplateError(f"{where}: {exc}") from exc
        code = persona.code_for(field_name, override)
        spans.append((cursor, cursor + len(value), value, code, f"{persona.persona_id}|{role}.{field_name}"))
        out.append(value)
        cursor += len(value)
        pos = m.end()
    tail = body[pos:].replace("{{", "{").replace("}}", "}")
    out.append(tail)
    return "".join(out), spans


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    document: Document
    labels: LabelSet
    template: str
    cast: Mapping[str, Persona]


def render(
    template: Template,
    personas: Mapping[str, Persona],
    *,
    doc_id: str,
) -> RenderedDocument:
    """Render one template with one cast into a document and its exact labels."""
    missing = template.roles_used - set(personas)
    if missing:
        raise TemplateError(
            f"{template.name}: no persona supplied for {sorted(missing)}; the cast line "
            f"declares {sorted(template.cast)}"
        )
    builders: dict[int, _PageBuilder] = {}
    for b in template.blocks:
        builder = builders.setdefault(b.page, _PageBuilder(number=b.page))
        if b.literal:
            rendered, spans = b.body, cast("list[tuple[int, int, str, str, str]]", [])
        else:
            rendered, spans = _render_block(
                b.body, personas, where=f"{template.name} block {b.kind}"
            )
        builder.add_block(b.kind, rendered, spans)

    pages = tuple(builders[n].build() for n in sorted(builders))
    labels = tuple(s for n in sorted(builders) for s in builders[n].labels)

    sender = personas.get("official") or next(iter(personas.values()))
    document = Document(
        doc_id=doc_id,
        doc_type=template.doc_type,
        pages=pages,
        metadata=DocumentMetadata(
            title=template.meta.get("title"),
            author=sender.full_name,
            subject=template.meta.get("subject"),
            source_note=f"Synthetic, rendered from template {template.name}. No real person.",
        ),
    )
    return RenderedDocument(
        document=document,
        labels=LabelSet(doc_id=doc_id, spans=labels, source=LabelSource.CONSTRUCTED),
        template=template.name,
        cast=dict(personas),
    )


def check_labels(rendered: RenderedDocument) -> Sequence[str]:
    """Assert that every label indexes the text it claims to. Cheap, and it runs on every
    generated document, because a corpus with silently wrong offsets produces a results
    table that is wrong in a way nobody can see."""
    problems: list[str] = []
    for span in rendered.labels:
        page = rendered.document.page(span.page)
        actual = page.slice(span.offsets)
        if actual != span.text:
            problems.append(
                f"{rendered.document.doc_id} p{span.page} "
                f"[{span.offsets.start}:{span.offsets.end}] label says {span.text!r} "
                f"but the page says {actual!r}"
            )
    return problems
