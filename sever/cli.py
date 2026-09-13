"""`sever`: the command line.

Every published number comes from `sever report`, and nothing in the README is typed by
hand. The other commands exist so the pieces can be run and inspected one at a time, which
is what makes the tool inspectable rather than a black box that emits a table.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from sever import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Context-dependent redaction proposals for access-to-information requests.",
)
taxonomy_app = typer.Typer(no_args_is_help=True, help="The exemption taxonomy.")
corpus_app = typer.Typer(no_args_is_help=True, help="The labelled evaluation corpus.")
app.add_typer(taxonomy_app, name="taxonomy")
app.add_typer(corpus_app, name="corpus")

DEFAULT_CORPUS = Path("corpus/generated")
DEFAULT_RESULTS = Path("results")


@app.callback()
def _root() -> None:
    """The tool proposes; a person decides. No command here releases a document."""


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"sever {__version__}")


# --- taxonomy -----------------------------------------------------------------


@taxonomy_app.command("render")
def taxonomy_render(
    out: Annotated[Path, typer.Option(help="Where to write the Markdown.")] = Path(
        "docs/taxonomy.md"
    ),
) -> None:
    """Regenerate docs/taxonomy.md from the YAML. Run this in the same commit as any
    change to the YAML; a test fails if the two disagree."""
    from sever.taxonomy.render_docs import write

    path = write(out)
    typer.echo(f"wrote {path}")


@taxonomy_app.command("check")
def taxonomy_check() -> None:
    """Validate the taxonomy and report how much of it has been verified against the
    consolidated statute texts."""
    from sever.taxonomy.loader import load_taxonomy

    t = load_taxonomy()
    typer.echo(f"{len(t.categories.codes)} codes, {len(t.jurisdictions)} jurisdictions")
    for key, (ok, total) in sorted(t.verification_summary().items()):
        name = t.jurisdictions[key].name
        typer.echo(f"  {name}: {ok} of {total} provisions verified")
        for code, mapping in t.jurisdictions[key].mappings.items():
            for p in mapping.provisions:
                if not p.is_verified:
                    typer.echo(f"    not checked: {code} {p.statute} s.{p.section}")


# --- corpus -------------------------------------------------------------------


@corpus_app.command("build")
def corpus_build(
    documents: Annotated[int, typer.Option(help="How many documents to render.")] = 60,
    seed: Annotated[int, typer.Option(help="Generator seed.")] = 20270802,
    out: Annotated[Path, typer.Option(help="Output directory.")] = DEFAULT_CORPUS,
) -> None:
    """Render the labelled corpus. Deterministic from the seed, free, and offline."""
    from sever.corpus.generate import build, write

    corpus = build(documents=documents, seed=seed)
    manifest = write(corpus, out)
    typer.echo(f"{len(corpus)} documents, {corpus.page_count} pages")
    typer.echo(f"labels by code: {corpus.label_counts()}")
    typer.echo(f"manifest: {manifest}")


@corpus_app.command("stats")
def corpus_stats(
    documents: Annotated[int, typer.Option()] = 60,
    seed: Annotated[int, typer.Option()] = 20270802,
) -> None:
    """Label counts without writing anything."""
    from sever.corpus.generate import build

    corpus = build(documents=documents, seed=seed)
    typer.echo(json.dumps(corpus.label_counts(), indent=1))


# --- the pipeline -------------------------------------------------------------


@app.command()
def propose(
    documents: Annotated[int, typer.Option(help="Corpus documents to run over.")] = 6,
    seed: Annotated[int, typer.Option()] = 20270802,
    show: Annotated[int, typer.Option(help="Proposals to print per document.")] = 8,
    sentence_only: Annotated[
        bool, typer.Option(help="Blank the document context: the ablation baseline.")
    ] = False,
) -> None:
    """Propose redactions over corpus documents and print them with their reasons."""
    from sever.corpus.generate import build
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.report import config_for

    detector = SeverDetector()
    for item in build(documents=documents, seed=seed):
        doc = item.rendered.document
        engine = DecisionEngine(
            config=config_for(item), detector=detector, sentence_only=sentence_only
        )
        proposals = engine.propose(doc)
        typer.echo(f"\n=== {doc.doc_id} ({doc.doc_type.value}) ===")
        typer.echo(f"{len(proposals)} spans; {len(proposals.withheld)} withheld; "
                   f"{len(proposals.escalations)} escalated; codes {proposals.by_code()}")
        for p in list(proposals)[:show]:
            typer.echo(f"  [{p.code}] {p.detection.text!r}")
            typer.echo(f"        {p.reason}")


@app.command()
def export(
    documents: Annotated[int, typer.Option()] = 3,
    seed: Annotated[int, typer.Option()] = 20270802,
    out: Annotated[Path, typer.Option(help="Where to write the PDFs.")] = Path("review/exports"),
    rasterise: Annotated[bool, typer.Option(help="Re-render pages as images.")] = False,
) -> None:
    """Produce truly redacted PDFs and their schedules, then run the leak test on them.

    This command exists to be run and the output opened. The claim "the text under the box
    is gone" is worth what the check behind it is worth.
    """
    from sever.corpus.generate import build
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.pdf_leak import LeakChecker
    from sever.eval.report import config_for
    from sever.review.export import apply_redactions, build_schedule, render_pdf

    out.mkdir(parents=True, exist_ok=True)
    detector = SeverDetector()
    checker = LeakChecker()
    for item in build(documents=documents, seed=seed):
        doc = item.rendered.document
        proposals = DecisionEngine(config=config_for(item), detector=detector).propose(doc)
        source = render_pdf(doc, out / f"{doc.doc_id}.pdf")
        result = apply_redactions(
            source, out / f"{doc.doc_id}-released.pdf", doc, proposals, rasterise=rasterise
        )
        schedule = build_schedule(doc.doc_id, doc, tuple(proposals))
        (out / f"{doc.doc_id}-schedule.md").write_text(schedule.to_markdown(), encoding="utf-8")
        checker.check(result.path, result.regions, document=doc.doc_id)
        typer.echo(f"{doc.doc_id}: {result.boxes} boxes, schedule {len(schedule.rows)} rows")
    report = checker.report()
    typer.echo("")
    typer.echo(report.summary())
    if not report.clean:
        for f in report.findings[:10]:
            typer.echo(f"  {f}")
        raise typer.Exit(code=1)


@app.command()
def report(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 60,
    seed: Annotated[int, typer.Option()] = 20270802,
    out: Annotated[Path, typer.Option(help="Where to write results.")] = DEFAULT_RESULTS,
    readme: Annotated[
        Path | None, typer.Option(help="Splice the tables into this README.")
    ] = None,
    pdf_leak: Annotated[bool, typer.Option(help="Run the PDF leak test too.")] = True,
) -> None:
    """Run every system over the corpus and write the published tables.

    This is the one command behind every number in the README.
    """
    from sever.eval import report as report_mod

    tmp = Path(tempfile.mkdtemp(prefix="sever-export-"))
    try:
        result = report_mod.run(
            documents=documents, seed=seed, with_pdf_leak=pdf_leak, tmp_dir=tmp
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    markdown = report_mod.to_markdown(result)
    md, js = report_mod.write(result, out)
    typer.echo(markdown)
    typer.echo(f"wrote {md} and {js}")
    if readme is not None:
        changed = report_mod.splice_into_readme(readme, markdown)
        typer.echo(f"{readme}: {'updated' if changed else 'already current'}")


@app.command()
def audit(
    path: Annotated[Path, typer.Argument(help="The audit database.")],
) -> None:
    """Verify an audit log's hash chain and print its rows."""
    from sever.review.audit import AuditLog

    with AuditLog(path) as log:
        ok, message = log.verify_chain()
        typer.echo(f"{'intact' if ok else 'BROKEN'}: {message}")
        for row in log:
            typer.echo(
                f"  {row.seq:4d} {row.at:%Y-%m-%d %H:%M} {row.actor:16} {row.action.value:15} "
                f"{row.doc_id} p{row.page} {row.proposed_code or '-'} -> {row.final_code or '-'}"
            )
        if not ok:
            raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
