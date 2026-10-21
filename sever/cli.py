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
from typing import TYPE_CHECKING, Annotated, Any

import typer

from sever import __version__
from sever.corpus.personas import PUBLIC_BODY_DOMAIN
from sever.gateway import DECISIONS_MINIMUM, BoundaryUnavailable, require_boundary

if TYPE_CHECKING:
    from sever.decide.model import GatewayModelDecider

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
# The trap templates, kept out of the headline corpus; see `eval_traps`.
TRAP_DIR = Path(__file__).parent / "corpus" / "traps"

# The gateway configuration is not in this repository and must not be: it names providers
# and points at a caps file, and this repository is public. The sibling checkout is the
# convenient default for the one machine that has it; BOUNDARY_CONFIG overrides it and is
# what anyone else would set.
DEFAULT_BOUNDARY_CONFIG = Path("../04-compliant-ai-gateway/config/boundary.yaml")


def _default_threshold(model_name: str) -> float:
    """The threshold a model runs at when none is given: a decision model has its own."""
    from sever.decide.decision_model import DEFAULT_DECISION_THRESHOLD, is_decision_model
    from sever.decide.pipeline import DEFAULT_THRESHOLD

    return DEFAULT_DECISION_THRESHOLD if is_decision_model(model_name) else DEFAULT_THRESHOLD


def _build_model(
    *,
    enabled: bool,
    model_name: str,
    boundary_config: Path | None,
    run_id: str | None,
    answer_cache: Path | None = None,
    replay_only: bool = False,
    public_body_domains: tuple[str, ...] = (),
) -> GatewayModelDecider | None:
    """Construct the model decider, or None.

    Every branch that can spend money goes through here, and it is deliberately loud: the
    command prints the gateway configuration, the model and the run id before the first
    call, because a spend that nobody saw start is the one that goes wrong.
    """
    if not enabled:
        return None
    import os
    import uuid

    from sever.decide.decision_model import DecisionModelDecider, is_decision_model
    from sever.decide.model import CAPS_PROJECT, DATA_CLASS, GatewayModelDecider

    # A decision model (Jev, Kev) is the same pipeline with the request reshaped; which one
    # is chosen by the provider entry the model id names. See sever/decide/decision_model.py.
    decider_cls: type[GatewayModelDecider] = (
        DecisionModelDecider if is_decision_model(model_name) else GatewayModelDecider
    )

    if replay_only:
        if answer_cache is None or not answer_cache.is_file():
            raise typer.BadParameter(
                "--replay-only needs an answer cache to replay. Point --answer-cache at "
                "the file a paid run recorded."
            )
        typer.echo(
            f"model layer ON, replaying {answer_cache} only: no gateway, no network, no "
            f"spend. A span the cache does not hold is an error rather than a call."
        )
        return decider_cls(
            gateway=None,
            model=model_name,
            enabled=True,
            run_id=run_id,
            cache_path=answer_cache,
            replay_only=True,
            public_body_domains=public_body_domains,
        )

    # Path("") is Path("."), which is truthy and is not a configuration file, so the
    # environment variable is checked as a string before it becomes a path.
    from_env = os.environ.get("BOUNDARY_CONFIG", "").strip()
    config = boundary_config or (Path(from_env) if from_env else DEFAULT_BOUNDARY_CONFIG)
    if not config.is_file():
        raise typer.BadParameter(
            f"no gateway configuration at {config}. Point --boundary-config or "
            f"BOUNDARY_CONFIG at a boundary.yaml whose caps file has an entry for "
            f"{CAPS_PROJECT!r}."
        )
    try:
        require_boundary(DECISIONS_MINIMUM if decider_cls is DecisionModelDecider else None)
        from boundary import Gateway
    except (BoundaryUnavailable, ImportError) as exc:
        raise typer.BadParameter(f"{exc} Or drop --model.") from exc

    gateway = Gateway.from_config(config, project=CAPS_PROJECT)
    run = run_id or f"sever-{uuid.uuid4().hex[:8]}"
    typer.echo(
        f"model layer ON: {model_name} through {config}, project {CAPS_PROJECT}, "
        f"data class {DATA_CLASS}, run id {run}"
    )
    if answer_cache is not None:
        state = "replaying" if answer_cache.is_file() else "new"
        typer.echo(
            f"answer cache: {answer_cache} ({state}). A span already in the cache is not "
            f"re-sent and costs nothing."
        )
    return decider_cls(
        gateway=gateway,
        model=model_name,
        enabled=True,
        run_id=run,
        cache_path=answer_cache,
        public_body_domains=public_body_domains,
    )


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
    names: Annotated[str, typer.Option(help="Name pool: 'plain' or 'nl'.")] = "plain",
) -> None:
    """Render the labelled corpus. Deterministic from the seed, free, and offline."""
    from sever.corpus.generate import build, write
    from sever.corpus.personas import NameProfile

    corpus = build(documents=documents, seed=seed, names=NameProfile(names))
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
    model: Annotated[
        bool, typer.Option("--model/--no-model", help="Send the residual to the gateway. Spends money.")
    ] = False,
    model_name: Annotated[str, typer.Option(help="Gateway model identifier.")] = "",
    boundary_config: Annotated[
        Path | None, typer.Option(help="Path to boundary.yaml. Defaults to BOUNDARY_CONFIG.")
    ] = None,
    run_id: Annotated[
        str | None, typer.Option(help="Ledger run id. The per-run spend cap is measured against it.")
    ] = None,
) -> None:
    """Propose redactions over corpus documents and print them with their reasons."""
    from sever.corpus.generate import build
    from sever.decide.model import DEFAULT_MODEL
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.report import config_for

    decider = _build_model(
        enabled=model,
        model_name=model_name or DEFAULT_MODEL,
        boundary_config=boundary_config,
        run_id=run_id,
        public_body_domains=(PUBLIC_BODY_DOMAIN,),
    )
    detector = SeverDetector()
    for item in build(documents=documents, seed=seed):
        doc = item.rendered.document
        engine = DecisionEngine(
            config=config_for(item),
            detector=detector,
            sentence_only=sentence_only,
            model=decider,
        )
        proposals = engine.propose(doc)
        typer.echo(f"\n=== {doc.doc_id} ({doc.doc_type.value}) ===")
        typer.echo(f"{len(proposals)} spans; {len(proposals.withheld)} withheld; "
                   f"{len(proposals.escalations)} escalated; codes {proposals.by_code()}")
        for p in list(proposals)[:show]:
            typer.echo(f"  [{p.code}] {p.detection.text!r}  ({p.source.value})")
            typer.echo(f"        {p.reason}")
    if decider is not None:
        typer.echo(f"\n{decider.spend_summary()}")


@app.command()
def export(
    documents: Annotated[int, typer.Option()] = 3,
    seed: Annotated[int, typer.Option()] = 20270802,
    out: Annotated[Path, typer.Option(help="Where to write the PDFs.")] = Path("review/exports"),
    rasterise: Annotated[bool, typer.Option(help="Re-render pages as images.")] = False,
    audit: Annotated[
        Path | None,
        typer.Option(help="A reviewed audit log. Without one, nothing is called released."),
    ] = None,
    request_id: Annotated[str, typer.Option(help="The request the log was reviewed under.")] = (
        "A-2027-001"
    ),
) -> None:
    """Apply the redactions and run the leak test on the result.

    This command exists to be run and the output opened. The claim "the text under the box
    is gone" is worth what the check behind it is worth.

    **What it will and will not call a release.** With `--audit` pointing at a log in which a
    person has completed every page of a document, the gate passes and the file is written as
    `-released.pdf`. Without one, the same redactions are applied and the same leak test runs,
    but the file is written as `-proposed.pdf`, because nobody has decided anything and a
    document nobody has reviewed is not a release however good the redactions are. That is
    the rule in CLAUDE.md, and until the reviewer application existed this command was
    quietly breaking it by writing "released" on files no person had seen.
    """
    from sever.corpus.generate import build
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.pdf_leak import LeakChecker
    from sever.eval.report import config_for
    from sever.review.decisions import as_released, final_spans
    from sever.review.export import apply_redactions, build_schedule, render_pdf
    from sever.taxonomy.loader import default_taxonomy

    taxonomy = default_taxonomy()

    out.mkdir(parents=True, exist_ok=True)
    detector = SeverDetector()
    checker = LeakChecker()
    reviewed: frozenset[tuple[str, int]] = frozenset()
    audit_rows: tuple[Any, ...] = ()
    if audit is not None:
        if not audit.is_file():
            raise typer.BadParameter(f"no audit log at {audit}")
        from sever.review.audit import AuditLog

        with AuditLog(audit) as log:
            ok, message = log.verify_chain()
            if not ok:
                raise typer.BadParameter(f"the audit log is not intact: {message}")
            reviewed = log.pages_reviewed(request_id)
            audit_rows = log.rows(request_id=request_id)
        typer.echo(f"audit log {audit}: {len(reviewed)} pages completed under {request_id}")
    else:
        typer.echo(
            "no --audit given, so nothing here is a release: the files are written as "
            "-proposed.pdf. The tool proposes; a person decides."
        )
    for item in build(documents=documents, seed=seed):
        doc = item.rendered.document
        proposals = DecisionEngine(config=config_for(item), detector=detector).propose(doc)
        outstanding = [p.number for p in doc if (doc.doc_id, p.number) not in reviewed]
        released = audit is not None and not outstanding
        if audit is not None and outstanding:
            typer.echo(
                f"{doc.doc_id}: pages {outstanding} have no reviewer action, so this is "
                f"written as proposed rather than released"
            )
        suffix = "released" if released else "proposed"
        if released:
            # What the reviewer decided, not what the tool proposed: a rejected proposal
            # stays in the record and a span the reviewer severed themselves goes.
            applied = as_released(
                final_spans(audit_rows, tuple(proposals), doc_id=doc.doc_id, taxonomy=taxonomy),
                tuple(proposals),
                doc,
                taxonomy=taxonomy,
            )
        else:
            applied = tuple(proposals)
        source = render_pdf(doc, out / f"{doc.doc_id}.pdf")
        result = apply_redactions(
            source, out / f"{doc.doc_id}-{suffix}.pdf", doc, applied, rasterise=rasterise
        )
        schedule = build_schedule(doc.doc_id, doc, applied)
        (out / f"{doc.doc_id}-schedule.md").write_text(schedule.to_markdown(), encoding="utf-8")
        checker.check(result.path, result.regions, document=doc.doc_id)
        typer.echo(
            f"{doc.doc_id}: {result.boxes} boxes, schedule {len(schedule.rows)} rows, {suffix}"
        )
    report = checker.report()
    typer.echo("")
    typer.echo(report.summary())
    if not report.clean:
        for f in report.findings[:10]:
            typer.echo(f"  {f}")
        raise typer.Exit(code=1)


@app.command()
def report(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
    out: Annotated[Path, typer.Option(help="Where to write results.")] = DEFAULT_RESULTS,
    readme: Annotated[
        Path | None, typer.Option(help="Splice the tables into this README.")
    ] = None,
    pdf_leak: Annotated[bool, typer.Option(help="Run the PDF leak test too.")] = True,
    jurisdiction: Annotated[
        str,
        typer.Option(help="Which statute to decide under: 'federal' or 'nl'."),
    ] = "federal",
    model_only: Annotated[
        bool,
        typer.Option(
            "--model-only/--no-model-only",
            help="Add the no-rules baseline. Roughly triples the spans sent.",
        ),
    ] = True,
    model: Annotated[
        bool,
        typer.Option(
            "--model/--no-model",
            help="Add the rules-then-model row. Spends money through the 04 gateway.",
        ),
    ] = False,
    model_name: Annotated[str, typer.Option(help="Gateway model identifier.")] = "",
    boundary_config: Annotated[
        Path | None, typer.Option(help="Path to boundary.yaml. Defaults to BOUNDARY_CONFIG.")
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option(help="Ledger run id. The per-run spend cap is measured against it."),
    ] = None,
    answer_cache: Annotated[
        Path | None,
        typer.Option(help="Replay model answers from here, and record new ones into it."),
    ] = None,
    threshold: Annotated[
        float, typer.Option(help="Below this confidence a model answer is escalated.")
    ] = -1.0,
    replay_only: Annotated[
        bool,
        typer.Option(
            "--replay-only",
            help="Read the answer cache and never send. Reproduces the model row for free.",
        ),
    ] = False,
    public_body_domain: Annotated[
        list[str] | None,
        typer.Option(
            help=(
                "The public body's own email domain. Repeat for several. Addresses on it "
                "reach the model as [EMAIL_PUBLIC_BODY_n] rather than [EMAIL_n]. Defaults "
                "to the synthetic corpus's body, which is what these commands measure."
            ),
        ),
    ] = None,
) -> None:
    """Run every system over the corpus and write the published tables.

    This is the one command behind every number in the README. Without --model it makes no
    network call and costs nothing, which is the configuration CI runs.
    """
    from sever.decide.model import DEFAULT_MODEL
    from sever.eval import report as report_mod
    from sever.eval.cost import DEFAULT_COST_PATH

    decider = _build_model(
        enabled=model,
        model_name=model_name or DEFAULT_MODEL,
        boundary_config=boundary_config,
        run_id=run_id,
        answer_cache=answer_cache,
        replay_only=replay_only,
        public_body_domains=tuple(public_body_domain or (PUBLIC_BODY_DOMAIN,)),
    )
    tmp = Path(tempfile.mkdtemp(prefix="sever-export-"))
    try:
        result = report_mod.run(
            documents=documents,
            seed=seed,
            with_pdf_leak=pdf_leak,
            tmp_dir=tmp,
            model=decider,
            jurisdiction=jurisdiction,
            with_model_only=model_only,
            model_confidence_threshold=None if threshold < 0 else threshold,
            # The recorded cost is the published model's; another model's run states its own
            # spend in the model line and gets no cost line it did not pay for.
            cost_path=(
                DEFAULT_COST_PATH
                if (model_name or DEFAULT_MODEL) == DEFAULT_MODEL
                else None
            ),
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


@app.command("eval-traps")
def eval_traps(
    documents: Annotated[int, typer.Option(help="Trap documents to render.")] = 30,
    seed: Annotated[int, typer.Option()] = 20271019,
    model: Annotated[
        bool,
        typer.Option("--model/--no-model", help="Add the rules-then-model row. Spends money."),
    ] = False,
    model_name: Annotated[str, typer.Option(help="Gateway model identifier.")] = "",
    boundary_config: Annotated[Path | None, typer.Option()] = None,
    run_id: Annotated[str | None, typer.Option()] = None,
    answer_cache: Annotated[
        Path | None, typer.Option(help="Replay model answers from here, and record new ones.")
    ] = Path("results/model-answers-traps.jsonl"),
    replay_only: Annotated[
        bool, typer.Option("--replay-only", help="Read the answer cache and never send.")
    ] = False,
    threshold: Annotated[
        float, typer.Option(help="Below this confidence a model answer is escalated.")
    ] = -1.0,
    out: Annotated[Path, typer.Option(help="Write the tables here.")] = Path(
        "results/traps.md"
    ),
) -> None:
    """The trap set: records written to break a rule, scored apart from the headline corpus.

    The headline corpus cannot test a rule it has no counter-example for. Every government
    email address in it belongs to an official doing their job, so "a work address is K2"
    could not leak there however wrong it was. The trap set holds the counter-examples
    (sever/corpus/traps/), and it is kept out of the headline corpus because adding a
    template there renumbers every document and would detach the frozen reviewer study
    from the records it was scored on.
    """
    from sever.corpus.generate import build
    from sever.decide.model import DEFAULT_MODEL
    from sever.eval import report as report_mod

    decider = _build_model(
        enabled=model,
        model_name=model_name or DEFAULT_MODEL,
        boundary_config=boundary_config,
        run_id=run_id,
        answer_cache=answer_cache,
        replay_only=replay_only,
        public_body_domains=(PUBLIC_BODY_DOMAIN,),
    )
    corpus = build(documents=documents, seed=seed, template_dir=TRAP_DIR)
    result = report_mod.run(
        corpus=corpus,
        with_pdf_leak=False,
        model=decider,
        with_model_only=False,
        cost_path=None,
        model_confidence_threshold=None if threshold < 0 else threshold,
    )
    markdown = (
        "# Trap set\n\nRecords written to break a rule, scored apart from the headline "
        "corpus. Generated by `sever eval-traps`; never hand-edited.\n\n"
        + report_mod.to_markdown(result).replace("by `sever report`", "by `sever eval-traps`")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown + "\n", encoding="utf-8")
    typer.echo(markdown)
    typer.echo(f"wrote {out}")


@app.command("eval-detector")
def eval_detector(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
    compare_boundary: Annotated[
        bool, typer.Option("--compare/--no-compare", help="Also run project 04's engine.")
    ] = True,
    names: Annotated[
        str,
        typer.Option(
            help="Name pool: 'plain' (the published corpus) or 'nl' (apostrophes, Mac/Mc, accents)."
        ),
    ] = "plain",
    out: Annotated[
        Path | None, typer.Option(help="Also write the tables to this file.")
    ] = None,
) -> None:
    """Detector recall per entity type, against labels known by construction.

    Project 04 shipped `boundary.redact` without measured recall. This project's corpus
    knows exactly what was inserted and where, so it can supply the number. Run with
    --compare to put 04's engine beside this project's.
    """
    from sever.corpus.generate import build
    from sever.corpus.personas import NameProfile
    from sever.detect.engine import SeverDetector
    from sever.eval.detector import compare as compare_reports
    from sever.eval.detector import evaluate

    profile = NameProfile(names)
    corpus = build(documents=documents, seed=seed, names=profile)
    if profile is not NameProfile.PLAIN:
        typer.echo(
            f"name pool: {profile.value}. The published tables are measured on 'plain'; "
            f"this run is the comparison in results/names.md."
        )
    reports = [evaluate(SeverDetector(), corpus)]
    if compare_boundary:
        try:
            from sever.detect.boundary_adapter import BoundaryDetector

            reports.append(evaluate(BoundaryDetector(), corpus))
        except Exception as exc:
            # The extra is optional; a missing model or package is not a failure here.
            typer.echo(f"boundary.redact not available, skipping the comparison: {exc}")

    lines: list[str] = []
    for r in reports:
        lines += ["", r.to_markdown()]
    if len(reports) > 1:
        lines += ["", "**Side by side, recall**", "", compare_reports(reports)]
    text = "\n".join(lines)
    typer.echo(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "<!-- Generated by `sever eval-detector`. Do not hand-edit. -->\n\n"
            "# Detector recall, measured against labels known by construction\n"
        )
        out.write_text(header + text + "\n", encoding="utf-8")
        typer.echo(f"\nwrote {out}")


@app.command("eval-names")
def eval_names(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
    compare_boundary: Annotated[
        bool, typer.Option("--compare/--no-compare", help="Also run project 04's engine.")
    ] = True,
    profiles: Annotated[
        str,
        typer.Option(
            help=(
                "Comma-separated name profiles, or 'published' for plain and nl, or "
                "'all' for every single-shape profile as well."
            )
        ),
    ] = "published",
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/names.md"
    ),
) -> None:
    """The same detectors on the same corpus with different name shapes.

    Corpora identical in every respect except the pool the personas' names are drawn from.
    `plain` is what every published number is measured on; `nl` swaps in apostrophes, Mac
    and Mc prefixes, accented letters, hyphens and two-token surnames, which are ordinary
    here and were entirely absent from the corpus.

    `--profiles all` adds one corpus per shape, each varying the surname alone, which is
    what attributes the difference to a cause instead of only reporting it.

    Free, offline, and it spends nothing.
    """
    from sever.corpus.generate import build
    from sever.corpus.personas import NameProfile
    from sever.detect.engine import SeverDetector
    from sever.eval.detector import compare as compare_reports
    from sever.eval.detector import evaluate

    if profiles == "published":
        wanted = [NameProfile.PLAIN, NameProfile.NL]
    elif profiles == "all":
        wanted = list(NameProfile)
    else:
        wanted = [NameProfile(p.strip()) for p in profiles.split(",") if p.strip()]

    reports = []
    for profile in wanted:
        typer.echo(f"building and evaluating the {profile.value} corpus ...")
        corpus = build(documents=documents, seed=seed, names=profile)
        report = evaluate(SeverDetector(), corpus)
        report.detector = f"sever, {profile.value}"
        reports.append(report)
        if compare_boundary:
            try:
                from sever.detect.boundary_adapter import BoundaryDetector

                other = evaluate(BoundaryDetector(), corpus)
                other.detector = f"boundary.redact, {profile.value}"
                reports.append(other)
            except Exception as exc:
                typer.echo(f"boundary.redact not available, skipping: {exc}")

    table = compare_reports(reports)
    typer.echo("")
    typer.echo(table)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "<!-- Generated by `sever eval-names`. Do not hand-edit. -->\n\n"
            "# What the province's own name shapes cost\n\n"
            "Corpora identical except for the pool the personas' names come from. `plain`\n"
            "is the published corpus and every other number in this repository is measured\n"
            "on it. `nl` swaps in the shapes that are ordinary in Newfoundland and Labrador\n"
            "and were entirely absent from `plain`: apostrophes (O'Brien, O'Keefe), Mac and\n"
            "Mc prefixes, accented letters, hyphenated surnames and two-token surnames\n"
            "(St. Croix, Le Drew).\n\n"
            "The remaining profiles carry one shape each, varying the surname alone with\n"
            "the forenames held at the plain pool, so that a difference can be attributed\n"
            "to a cause rather than only observed. Holding the forenames plain understates\n"
            "each shape a little, which is the right direction for an attribution.\n\n"
            "Nothing else differs between any two columns: same templates, same seed, same\n"
            "roles, same cast sizes. Regenerate with `sever eval-names --profiles all`.\n\n"
            "**Read the two engines with one difference in mind.** `sever` runs the\n"
            "document-wide name sweep described in `results/sweep.md`, which recovers a\n"
            "person's other mentions once the record has named them anywhere, and\n"
            "`boundary.redact` has no equivalent. So this compares what each engine ships,\n"
            "not the models underneath. The sweep accounts for most of the gap: with it\n"
            "switched off `sever` scores 96.2 on `plain` and 93.4 on `nl`, within a point\n"
            "of the column beside it. `results/sweep.md` is the honest place to read the\n"
            "underlying detectors against each other.\n\n"
            + table
            + "\n",
            encoding="utf-8",
        )
        typer.echo(f"\nwrote {out}")


@app.command("eval-sweep")
def eval_sweep(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
    profiles: Annotated[
        str, typer.Option(help="Comma-separated name profiles, or 'published', or 'all'.")
    ] = "all",
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/sweep.md"
    ),
) -> None:
    """What the document-wide name sweep is worth, per name profile.

    The same detector twice over the same corpus, once with the sweep off and once with it
    on. Nothing else differs, so the pair is an ablation rather than two runs.

    Free, offline, and it spends nothing.
    """
    from sever.corpus.generate import build
    from sever.corpus.personas import NameProfile
    from sever.detect.engine import SeverDetector
    from sever.eval.detector import compare as compare_reports
    from sever.eval.detector import evaluate

    if profiles == "published":
        wanted = [NameProfile.PLAIN, NameProfile.NL]
    elif profiles == "all":
        wanted = list(NameProfile)
    else:
        wanted = [NameProfile(x.strip()) for x in profiles.split(",") if x.strip()]

    reports = []
    for profile in wanted:
        typer.echo(f"evaluating {profile.value} with and without the sweep ...")
        corpus = build(documents=documents, seed=seed, names=profile)
        for sweeping in (False, True):
            report = evaluate(SeverDetector(sweep_names=sweeping), corpus)
            report.detector = f"{profile.value}, {'sweep' if sweeping else 'no sweep'}"
            reports.append(report)

    table = compare_reports(reports)
    typer.echo("")
    typer.echo(table)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "<!-- Generated by `sever eval-sweep`. Do not hand-edit. -->\n\n"
            "# What the document-wide name sweep recovers\n\n"
            "The same detector over the same corpus twice: once with the sweep off, once\n"
            "with it on. Every person the page detectors find licenses the other whole-word\n"
            "occurrences of their name parts across the rest of the document, which is the\n"
            "trick `sever.decide.placeholders` already used for the outbound boundary.\n\n"
            "The columns are paired per name profile, so each pair isolates the sweep and\n"
            "the pairs together show where it matters. It should do almost nothing on\n"
            "`plain`, whose names the model already knows, and most on the profiles whose\n"
            "names it does not.\n\n"
            + table
            + "\n",
            encoding="utf-8",
        )
        typer.echo(f"\nwrote {out}")


@app.command("eval-placeholders")
def eval_placeholders(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 60,
    seed: Annotated[int, typer.Option()] = 20270802,
    model: Annotated[
        str, typer.Option(help="A model on this machine. Anything else is refused.")
    ] = "local/qwen2.5:7b",
    boundary_config: Annotated[Path | None, typer.Option()] = None,
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/placeholders.md"
    ),
) -> None:
    """What the privacy boundary does to accuracy: the paired placeholders ablation.

    The same spans decided twice by the same model, once on typed placeholders and once on
    the raw record. The raw arm sends names, so it runs only against a model on this
    machine: the provider must be price-zero, declare single-region residency and answer on
    loopback, and the run refuses before it builds a payload otherwise.

    Spends nothing, and needs no vendor key.
    """
    import os

    from sever.eval import placeholders as ablation

    config = boundary_config or Path(
        os.environ.get("BOUNDARY_CONFIG", "").strip() or DEFAULT_BOUNDARY_CONFIG
    )
    if not config.is_file():
        raise typer.BadParameter(f"no gateway configuration at {config}")
    try:
        from boundary import Gateway
    except ImportError as exc:
        raise typer.BadParameter("boundary is not installed; see sever/gateway.py") from exc

    from sever.decide.model import CAPS_PROJECT

    gateway = Gateway.from_config(config, project=CAPS_PROJECT)
    try:
        ablation.assert_loopback(gateway, model)
    except ablation.NotLoopback as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"both arms on {model}, over loopback. Nothing leaves this machine.")

    result = ablation.run(gateway=gateway, model=model, documents=documents, seed=seed)
    typer.echo("")
    typer.echo(result.to_markdown())
    if out is not None:
        typer.echo(f"\nwrote {ablation.write(result, out)}")


@app.command("eval-thresholds")
def eval_thresholds(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
    answer_cache: Annotated[
        Path, typer.Option(help="The model answers to sweep over.")
    ] = Path("results/model-answers.jsonl"),
    model_name: Annotated[str, typer.Option(help="Gateway model identifier.")] = "",
    boundary_config: Annotated[Path | None, typer.Option()] = None,
    run_id: Annotated[str | None, typer.Option()] = None,
    replay_only: Annotated[
        bool, typer.Option("--replay-only", help="Read the cache and never send.")
    ] = True,
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/thresholds.md"
    ),
    public_body_domain: Annotated[
        list[str] | None,
        typer.Option(
            help=(
                "The public body's own email domain. Repeat for several. Addresses on it "
                "reach the model as [EMAIL_PUBLIC_BODY_n] rather than [EMAIL_n]. Defaults "
                "to the synthetic corpus's body, which is what these commands measure."
            ),
        ),
    ] = None,
) -> None:
    """Sweep the model confidence threshold against one set of model answers.

    Reads the answer cache, so a sweep over a cache that already covers the corpus makes no
    call and spends nothing. A span the cache does not hold is sent, which is how the cache
    is filled in the first place.
    """
    from sever.decide.model import DEFAULT_MODEL
    from sever.eval import thresholds as sweep_mod

    decider = _build_model(
        enabled=True,
        model_name=model_name or DEFAULT_MODEL,
        boundary_config=boundary_config,
        run_id=run_id,
        answer_cache=answer_cache,
        replay_only=replay_only,
        public_body_domains=tuple(public_body_domain or (PUBLIC_BODY_DOMAIN,)),
    )
    assert decider is not None
    result = sweep_mod.sweep(decider, documents=documents, seed=seed)
    typer.echo("")
    typer.echo(result.to_markdown())
    if out is not None:
        typer.echo(f"\nwrote {sweep_mod.write(result, out)}")


@app.command("eval-sample")
def eval_sample(
    sample: Annotated[
        Path, typer.Option(help="The frozen sample of residual spans.")
    ] = Path("data/decision-sample.json"),
    out: Annotated[Path | None, typer.Option(help="Write the tables here.")] = Path(
        "results/decision-sample.md"
    ),
) -> None:
    """Haiku 5.5, Jev and two Kev sizes on one sample of the residual, from their caches.

    Replay only: no gateway, no network, no spend. A span a cache does not hold is counted
    as unanswered. See sever/eval/decision_sample.py for what is scored.
    """
    from sever.eval import decision_sample as sample_mod

    sampled, scores = sample_mod.run(sample)
    typer.echo(sample_mod.to_markdown(sampled, scores))
    if out is not None:
        typer.echo(f"\nwrote {sample_mod.write(sampled, scores, out)}")


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


@app.command()
def cost(
    runs: Annotated[
        str,
        typer.Option(help="Comma-separated ledger runs that paid for the committed answers."),
    ] = "",
    pages: Annotated[int, typer.Option(help="Pages the published table covers.")] = 210,
    documents: Annotated[int, typer.Option()] = 210,
    asks: Annotated[
        int, typer.Option(help="Times the model layer asked. Read from results.json if 0.")
    ] = 0,
    answer_cache: Annotated[
        Path, typer.Option(help="The committed answers, one line each.")
    ] = Path("results/model-answers.jsonl"),
    results: Annotated[Path, typer.Option(help="Where --asks is read from.")] = Path(
        "results/results.json"
    ),
    boundary_config: Annotated[Path | None, typer.Option()] = None,
    out: Annotated[Path | None, typer.Option(help="Record it here for `sever report`.")] = Path(
        "results/cost.json"
    ),
    since: Annotated[
        str, typer.Option(help="Ignore ledger rows before this UTC timestamp.")
    ] = "",
    model_name: Annotated[
        str, typer.Option(help="The model the answers came from. Defaults to the published one.")
    ] = "",
) -> None:
    """Cost per page, out of the gateway ledger.

    Needs project 04's ledger, so it runs on this machine and not in CI. What it writes is
    committed, and `sever report` reads that file: the same arrangement as the answer
    cache, and for the same reason. A cloned repository can read the number and see which
    run and which date it came from, without holding the private dependency that produced
    it.
    """
    import os

    from sever.decide.model import CAPS_PROJECT
    from sever.eval import cost as cost_mod

    config = boundary_config or Path(
        os.environ.get("BOUNDARY_CONFIG", "").strip() or DEFAULT_BOUNDARY_CONFIG
    )
    if not config.is_file():
        raise typer.BadParameter(f"no gateway configuration at {config}")
    try:
        from boundary import Gateway
        from boundary.ledger import LedgerStore
    except ImportError as exc:
        raise typer.BadParameter("boundary is not installed; see sever/gateway.py") from exc

    gateway = Gateway.from_config(config, project=CAPS_PROJECT)
    store = LedgerStore(Path(gateway.config.ledger.path))
    if not answer_cache.is_file():
        raise typer.BadParameter(
            f"the committed answers are the check on the run list, and there are none at "
            f"{answer_cache}"
        )
    cached = sum(1 for line in answer_cache.open(encoding="utf-8") if line.strip())
    total_asks = asks
    if not total_asks:
        if not results.is_file():
            raise typer.BadParameter(f"pass --asks, or run `sever report` first ({results})")
        total_asks = int(json.loads(results.read_text(encoding="utf-8")).get("model_asks") or 0)
    if not total_asks:
        raise typer.BadParameter(
            "the results file does not record how many times the model layer was asked, "
            "so the deduplication figure has no denominator. Re-run `sever report` with "
            "the model on, or pass --asks."
        )
    run_ids = (
        tuple(r.strip() for r in runs.split(",") if r.strip())
        if runs
        else cost_mod.PUBLISHED_RUNS
    )
    if not runs and not since:
        since = cost_mod.PUBLISHED_SINCE
    # Which answers the pipeline asked for, by replaying it alone over the committed cache.
    # This is what splits a run that paid for the model-only baseline too; see
    # `cost_mod.from_ledger`. Free: replay-only, no gateway.
    from sever.decide.model import DEFAULT_MODEL
    from sever.eval import report as report_mod

    replay = _build_model(
        enabled=True,
        model_name=model_name or DEFAULT_MODEL,
        boundary_config=None,
        run_id=None,
        answer_cache=answer_cache,
        replay_only=True,
        public_body_domains=(PUBLIC_BODY_DOMAIN,),
    )
    assert replay is not None
    report_mod.run(
        documents=documents, with_pdf_leak=False, model=replay, with_model_only=False,
        cost_path=None,
    )
    answer_keys = [
        str(json.loads(line)["key"])
        for line in answer_cache.open(encoding="utf-8")
        if line.strip()
    ]
    try:
        result = cost_mod.from_ledger(
            ledger=store,
            project=CAPS_PROJECT,
            run_ids=run_ids,
            pages=pages,
            documents=documents,
            cached_answers=cached,
            asks=total_asks,
            since=since or None,
            answer_keys=answer_keys,
            pipeline_keys=frozenset(replay.keys_seen),
        )
    except (LookupError, cost_mod.LedgerMismatch) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(result.to_markdown())
    if out is not None:
        typer.echo(f"wrote {cost_mod.write(result, out)}")


releases_app = typer.Typer(no_args_is_help=True, help="Published federal release packages.")
app.add_typer(releases_app, name="releases")


@releases_app.command("add")
def releases_add(
    pdf: Annotated[Path, typer.Argument(help="A downloaded release package.")],
    source_url: Annotated[str, typer.Option(help="Where it was downloaded from.")],
    institution: Annotated[str, typer.Option(help="Which public body released it.")] = "",
    request_number: Annotated[str, typer.Option()] = "",
    note: Annotated[str, typer.Option()] = "",
    manifest: Annotated[Path, typer.Option()] = Path("data/releases/manifest.json"),
) -> None:
    """Record a downloaded package in the committed manifest, with its checksum.

    The PDFs are not committed and the manifest is, so anyone can download the same
    packages from the same URLs and reproduce the number, or get a checksum failure naming
    the file that differs. There is no fetcher on purpose; see `sever/ingest/releases.py`.
    """
    from sever.ingest import releases

    try:
        record = releases.add(
            pdf,
            source_url=source_url,
            institution=institution,
            request_number=request_number,
            note=note,
            manifest=manifest,
        )
    except releases.ManifestError as exc:
        raise typer.BadParameter(str(exc)) from exc
    check = releases.inspect_redaction(pdf)
    typer.echo(f"recorded {record.file_name} sha256 {record.sha256[:16]} in {manifest}")
    if check.sound:
        typer.echo(f"redaction check: {check.boxes} boxes, none with text under them")
    elif check.checked:
        typer.echo(
            f"REFUSED BY THE REDACTION CHECK: {check.boxes_with_text} of {check.boxes} "
            f"boxes still have text under them. This package's visible text carries values "
            f"a reviewer withheld, so it will be excluded from the measurement."
        )
    else:
        typer.echo(f"redaction check: not run, {check.note}")


@releases_app.command("check")
def releases_check(
    manifest: Annotated[Path, typer.Option()] = Path("data/releases/manifest.json"),
    root: Annotated[Path, typer.Option()] = Path("data/releases"),
) -> None:
    """Verify every package in the manifest is present, unmodified and soundly redacted."""
    from sever.ingest import releases

    loaded = releases.load(manifest, root)
    for r in loaded.releases:
        typer.echo(
            f"  ok  {r.record.file_name}: {len(r.document)} pages, "
            f"{r.scorable_pages} with visible text, {r.redaction.boxes} boxes"
        )
    for reason in loaded.excluded:
        typer.echo(f"  no  {reason}")
    typer.echo(f"{len(loaded.releases)} usable, {len(loaded.excluded)} excluded")


@app.command("eval-releases")
def eval_releases(
    manifest: Annotated[Path, typer.Option()] = Path("data/releases/manifest.json"),
    root: Annotated[Path, typer.Option()] = Path("data/releases"),
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/releases.md"
    ),
    held_out: Annotated[
        bool, typer.Option(help="The manifest is held out: chosen and scored blind.")
    ] = False,
    model: Annotated[
        bool,
        typer.Option("--model/--no-model", help="Send the rules' residual to the model. Spends money."),
    ] = False,
    model_name: Annotated[str, typer.Option(help="Gateway model identifier.")] = "",
    boundary_config: Annotated[Path | None, typer.Option()] = None,
    run_id: Annotated[str | None, typer.Option()] = None,
    answer_cache: Annotated[
        Path | None, typer.Option(help="Replay model answers from here, and record new ones.")
    ] = Path("results/model-answers-releases.jsonl"),
    replay_only: Annotated[
        bool, typer.Option("--replay-only", help="Read the answer cache and never send.")
    ] = False,
) -> None:
    """Over-redaction on records a public body actually released.

    The only track whose ground truth nobody in this project chose. A span still visible in
    a completed release was judged releasable by a reviewer, so a box over it is an
    over-redaction against a real decision. Leak rate is not computable here and is not
    reported.
    """
    from sever.decide.model import DEFAULT_MODEL
    from sever.eval import releases as releases_eval

    # No public body domain: these are federal records from several bodies, and a domain
    # the operator did not state is not one this command should guess.
    decider = _build_model(
        enabled=model,
        model_name=model_name or DEFAULT_MODEL,
        boundary_config=boundary_config,
        run_id=run_id,
        answer_cache=answer_cache,
        replay_only=replay_only,
    )
    result = releases_eval.run(
        manifest=manifest, root=root, held_out=held_out, model=decider,
        threshold=None,
    )
    typer.echo(result.to_markdown())
    if out is not None:
        typer.echo(f"wrote {releases_eval.write(result, out)}")


@app.command("eval-layout")
def eval_layout(
    documents: Annotated[int, typer.Option(help="Corpus size.")] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/layout.md"
    ),
) -> None:
    """What the layout is worth, and how much of it reads back from text alone.

    Scores the corpus three ways, with the rendered blocks, with every paragraph BODY, and
    with the blocks read back by `recover_blocks`, and says per labelled span whether the
    recovery put it in the right kind of block. Native text, rules only, spends nothing.
    """
    from sever.eval import layout as layout_eval

    result = layout_eval.run(documents=documents, seed=seed)
    typer.echo(result.to_markdown())
    if out is not None:
        typer.echo(f"wrote {layout_eval.write(result, out)}")


@app.command("eval-scanned")
def eval_scanned(
    documents: Annotated[int, typer.Option(help="Documents to scan. This track is slow.")] = 50,
    seed: Annotated[int, typer.Option()] = 20270802,
    profiles: Annotated[
        str, typer.Option(help="Comma-separated: clean, scanner, photocopy, fax.")
    ] = "",
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/scanned.md"
    ),
) -> None:
    """The scanned track: character error rate, and what it costs the decisions.

    Renders each document, degrades it the way a scanner does, reads it back with
    Tesseract, re-projects the labels through a character alignment and scores the
    pipeline on what the OCR produced. Needs Tesseract, which is a system binary rather
    than a Python package. Spends nothing.
    """
    from sever.eval import scanned as scan_mod
    from sever.ingest.ocr import PROFILES, TesseractMissing

    chosen = tuple(p.strip() for p in profiles.split(",") if p.strip()) or tuple(PROFILES)
    unknown = [p for p in chosen if p not in PROFILES]
    if unknown:
        raise typer.BadParameter(f"unknown profile(s) {unknown}; choose from {sorted(PROFILES)}")
    typer.echo(
        f"{documents} documents over {len(chosen)} profiles: {', '.join(chosen)}. "
        f"Every page is rasterised and read by a separate process, so this is slow."
    )
    try:
        result = scan_mod.run(documents=documents, seed=seed, profiles=chosen)
    except TesseractMissing as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo("")
    typer.echo(result.to_markdown())
    if out is not None:
        typer.echo(f"wrote {scan_mod.write(result, out)}")


@app.command("eval-reviewer")
def eval_reviewer(
    timings: Annotated[
        list[Path] | None,
        typer.Option("--timings", help="Timing files to read. Repeatable."),
    ] = None,
    audit: Annotated[
        Path | None,
        typer.Option(help="The audit log, to count completed pages that went untimed."),
    ] = None,
    request_id: Annotated[str | None, typer.Option()] = None,
    out: Annotated[Path | None, typer.Option(help="Write the table here.")] = Path(
        "results/reviewer.md"
    ),
) -> None:
    """Reviewer minutes per page, with and without proposals.

    Reads what `sever review` recorded. This is the one number in the definition of done
    that cannot be computed: somebody has to review the records. The command reports what
    has been collected and says plainly when that is not yet a result.
    """
    from sever.eval import reviewer

    study = reviewer.run(
        timings or [reviewer.DEFAULT_TIMINGS], audit=audit, request_id=request_id
    )
    typer.echo(study.to_markdown())
    if out is not None:
        typer.echo(f"wrote {reviewer.write(study, out)}")


def _session_for(
    *,
    request_id: str,
    documents: int,
    seed: int,
    mode: str,
    log_path: Path,
    timings: Path | None,
    actor: str | None,
) -> Any:
    """Build a review session over freshly generated corpus documents."""
    from sever.corpus.generate import build
    from sever.decide.pipeline import DecisionEngine
    from sever.detect.engine import SeverDetector
    from sever.eval.report import config_for
    from sever.review.session import Item, Mode, build_session

    detector = SeverDetector()
    items = []
    for corpus_item in build(documents=documents, seed=seed):
        doc = corpus_item.rendered.document
        proposals = DecisionEngine(config=config_for(corpus_item), detector=detector).propose(doc)
        items.append(Item(document=doc, proposals=tuple(proposals)))
    return build_session(
        request_id=request_id,
        items=items,
        log_path=log_path,
        mode=Mode(mode),
        timings_path=timings,
        actor=actor,
    )


@app.command()
def review(
    documents: Annotated[int, typer.Option(help="Corpus documents to put under review.")] = 3,
    seed: Annotated[int, typer.Option()] = 20270802,
    request_id: Annotated[str, typer.Option(help="The access request these belong to.")] = (
        "A-2027-001"
    ),
    mode: Annotated[
        str,
        typer.Option(help="'proposals' or 'unaided'. The two arms of the time study."),
    ] = "proposals",
    log: Annotated[Path, typer.Option(help="The append-only audit log.")] = Path(
        "review/audit.duckdb"
    ),
    timings: Annotated[Path, typer.Option(help="Per-page timings, one JSON object a line.")] = (
        Path("review/timings.jsonl")
    ),
    actor: Annotated[str | None, typer.Option(help="Who is reviewing. Defaults to the login.")] = (
        None
    ),
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
) -> None:
    """Open the reviewer's screen: one page at a time, an action on every span.

    Binds to loopback by default and has no authentication, because it is one reviewer on
    one machine. Do not put it on a network without putting something in front of it.

    The two modes are the arms of the reviewer time study. `proposals` shows what the tool
    proposed and why; `unaided` serves the same records with the proposals dropped before
    they reach the session, so the control cannot be undone by editing a template.
    """
    import uvicorn

    from sever.review.app import create_app
    from sever.review.session import Mode

    if mode not in {m.value for m in Mode}:
        raise typer.BadParameter(f"mode is 'proposals' or 'unaided', not {mode!r}")
    session = _session_for(
        request_id=request_id,
        documents=documents,
        seed=seed,
        mode=mode,
        log_path=log,
        timings=timings,
        actor=actor,
    )
    total_pages = sum(len(i.document) for i in session)
    typer.echo(
        f"request {request_id}: {len(session.items)} documents, {total_pages} pages, "
        f"mode {mode}"
    )
    typer.echo(f"audit log {log}; timings {timings}")
    if host == "127.0.0.1":
        chosen = _free_port(port)
        if chosen != port:
            typer.echo(f"port {port} is in use, so using {chosen}")
        port = chosen
    typer.echo(f"http://{host}:{port}")
    uvicorn.run(create_app(session), host=host, port=port, log_level="warning")


@app.command("eval-directory")
def eval_directory(
    documents: Annotated[int, typer.Option()] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
    out: Annotated[Path, typer.Option(help="Write the table here.")] = Path(
        "results/directory.md"
    ),
) -> None:
    """What a published staff directory buys in over-redaction, and costs in leaks.

    Rules only, nothing spent: no directory, then 50, 80 and 100 percent of the corpus's
    officials listed.
    """
    from sever.eval import directory

    rows = directory.run(documents=documents, seed=seed)
    typer.echo(directory.to_markdown(rows))
    typer.echo(f"wrote {directory.write(rows, out)}")

@app.command("gate-export")
def gate_export(
    out: Annotated[Path, typer.Option(help="Where to write the spec and both sides.")] = Path(
        "gate"
    ),
    answer_cache: Annotated[
        Path, typer.Option(help="The committed model answers, replayed.")
    ] = Path("results/model-answers.jsonl"),
    documents: Annotated[int, typer.Option()] = 210,
    seed: Annotated[int, typer.Option()] = 20270802,
) -> None:
    """Write what project 03's release gate needs: a spec and one file per side.

    Rules only against rules then the model, one suite per category, the document as the
    item. The model side is replayed from the answer cache, so this spends nothing. Then,
    from a checkout of 03: `uv run gate compare --spec <out>/spec.yaml --baseline
    <out>/rules-only.json --candidate <out>/rules-then-model.json --ledger <out>/ledger.jsonl`.
    """
    import subprocess

    import yaml

    from sever.decide.model import DEFAULT_MODEL
    from sever.eval import gate
    from sever.eval import report as report_mod

    decider = _build_model(
        enabled=True,
        model_name=DEFAULT_MODEL,
        boundary_config=None,
        run_id=None,
        answer_cache=answer_cache,
        replay_only=True,
        # The same request `sever report` sent, or the replay finds nothing to replay.
        public_body_domains=(PUBLIC_BODY_DOMAIN,),
    )
    result = report_mod.run(
        documents=documents,
        seed=seed,
        with_pdf_leak=False,
        model=decider,
        with_model_only=False,
    )
    systems = {s.name: s.scored for s in result.systems}
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    source = {"repository": "access-to-information-redaction", "commit": commit,
              "corpus": f"{documents} documents, seed {seed}"}
    cost = result.cost
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.yaml").write_text(
        "# Generated by `sever gate-export`. Do not hand-edit.\n"
        + yaml.safe_dump(gate.spec(), sort_keys=False),
        encoding="utf-8",
    )
    baseline = gate.side("sever, rules only", systems["sever, rules only"], source=source)
    candidate = gate.side(
        "sever, rules then the model on the residual",
        systems["sever, rules then the model on the residual"],
        source={**source, "model": DEFAULT_MODEL, "answers": str(answer_cache)},
        calls=cost.pipeline_calls if cost is not None else 0,
        cost_usd=cost.pipeline_cost_usd if cost is not None else 0.0,
        uncosted_calls=0,
    )
    for name, body in (("rules-only.json", baseline), ("rules-then-model.json", candidate)):
        (out / name).write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for key in baseline["suites"]:
        b = baseline["suites"][key]["outcomes"]
        c = candidate["suites"][key]["outcomes"]
        typer.echo(
            f"{key}: {len(b)} documents; right {sum(b.values())} rules only, "
            f"{sum(c.values())} with the model"
        )
    typer.echo(f"wrote {out}/spec.yaml, rules-only.json, rules-then-model.json")


@app.command()
def demo(
    host: Annotated[str, typer.Option(help="Bind address. 0.0.0.0 inside a container.")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option()] = 8000,
    insecure_cookie: Annotated[
        bool, typer.Option(help="Drop the cookie's Secure flag, for a local run over http.")
    ] = False,
    site: Annotated[
        Path | None,
        typer.Option(help="The built website (`sever site`). Built from the records if absent."),
    ] = None,
    released: Annotated[
        bool,
        typer.Option(
            help="Also serve the released pages in data/demo (`sever demo-records` builds them)."
        ),
    ] = True,
    model: Annotated[
        bool,
        typer.Option(
            "--model/--no-model",
            help="Replay Jev's recorded answers (`sever demo-answers`). Never calls a model.",
        ),
    ] = True,
    stats_file: Annotated[
        Path | None,
        typer.Option(
            help="Keep the dashboard's totals across restarts in this JSON file: read at start, "
            "saved every half minute and on exit. Counts only, as /dashboard.json publishes."
        ),
    ] = None,
) -> None:
    """The public demonstration: the project's website, the live dashboard, and one private,
    forgotten reviewer session per visitor.

    Six synthetic records and ten short excerpts of published releases, proposed by the
    rules and then Jev 1.14, whose answers are replayed from a committed file: no gateway,
    no network and no spend. Meant to run behind a TLS proxy; see docs/deploy.md.
    """
    import uvicorn

    from sever.review.demo import DemoServer, demo_items, demo_model, released_items

    typer.echo("preparing the demonstration records...")
    invented = demo_model(public_body_domains=(PUBLIC_BODY_DOMAIN,)) if model else None
    items = demo_items(model=invented)
    if site is None:
        from sever.site import build as build_site

        site = Path(tempfile.mkdtemp(prefix="sever-site-"))
        build_site(site, items=items)
    if released:
        items = items + released_items(model=demo_model() if model else None)
    server = DemoServer(items=items, site=site, secure_cookie=not insecure_cookie)
    if stats_file is not None:
        from sever.review.stats import keep

        assert server.stats is not None
        keep(server.stats, stats_file)
    typer.echo(f"http://{host}:{port}/")
    uvicorn.run(server, host=host, port=port, log_level="warning", access_log=False)

@app.command("demo-answers")
def demo_answers(
    boundary_config: Annotated[Path | None, typer.Option()] = None,
    run_id: Annotated[str, typer.Option(help="Ledger run id.")] = "sever-jev114-demo",
    released: Annotated[
        bool, typer.Option(help="Record answers for the released pages in data/demo too.")
    ] = True,
) -> None:
    """Record Jev's answers for the demonstration's records, through the 04 gateway.

    Spends money, once: the demonstration replays this file and never calls a model. A span
    already in the file is not sent again.
    """
    import os

    from sever.decide.model import CAPS_PROJECT, DEFAULT_MODEL
    from sever.review.demo import DEMO_ANSWERS, demo_items, demo_model, released_items

    from_env = os.environ.get("BOUNDARY_CONFIG", "").strip()
    config = boundary_config or (Path(from_env) if from_env else DEFAULT_BOUNDARY_CONFIG)
    if not config.is_file():
        raise typer.BadParameter(f"no gateway configuration at {config}")
    require_boundary(DECISIONS_MINIMUM)
    from boundary import Gateway

    gateway = Gateway.from_config(config, project=CAPS_PROJECT)
    typer.echo(
        f"model layer ON: {DEFAULT_MODEL} through {config}, project {CAPS_PROJECT}, run id "
        f"{run_id}, recording into {DEMO_ANSWERS}"
    )
    invented = demo_model(
        gateway=gateway, run_id=run_id, public_body_domains=(PUBLIC_BODY_DOMAIN,)
    )
    items = demo_items(model=invented)
    typer.echo(f"{len(items)} invented records: {invented.spend_summary()}")
    if released:
        pages = demo_model(gateway=gateway, run_id=run_id)
        typer.echo(f"{len(released_items(model=pages))} released records: {pages.spend_summary()}")


@app.command("demo-records")
def demo_records(
    manifest: Annotated[Path, typer.Option(help="The excerpts to build.")] = Path(
        "data/demo/manifest.json"
    ),
    releases: Annotated[
        Path, typer.Option(help="Where the downloaded release packages are.")
    ] = Path("data/releases"),
    out: Annotated[Path, typer.Option(help="Where to write the excerpts.")] = Path("data/demo"),
) -> None:
    """Build the demonstration's released pages from the packages in data/releases, checking
    each package's sha256 against the manifest first (PLAN.md 12.46)."""
    from sever.ingest.excerpts import ExcerptError, build

    try:
        written = build(manifest, releases, out)
    except ExcerptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    for path in written:
        typer.echo(f"wrote {path}")


@app.command()
def site(
    out: Annotated[Path, typer.Option(help="Where to write the website.")] = Path("site"),
    public: Annotated[
        bool,
        typer.Option(help="Link into the repository. Only once the repository is public."),
    ] = False,
) -> None:
    """Build the project's website from the results files, the taxonomy and the
    demonstration's records. Fails if any figure it prints cannot be read."""
    from sever.site import build as build_site

    typer.echo("running the demonstration's records through the engine...")
    built = build_site(out, public=public)
    typer.echo(f"wrote {', '.join(built.pages)} and their files to {built.out} ({built.figures} figures)")


def _free_port(start: int, tries: int = 20) -> int:
    """`start` if nothing is listening on it, otherwise the next free port above it.

    The person running the study should not have to know what a port is. The first time
    `sever study` met a `sever review` left running from earlier, it printed the address,
    then failed to bind it, which looks exactly like a tool that does not work.
    """
    import socket

    for candidate in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise typer.BadParameter(f"no free port between {start} and {start + tries - 1}")

study_app = typer.Typer(help="The reviewer time study: one command per reviewer.")
app.add_typer(study_app, name="study")


@study_app.callback(invoke_without_command=True)
def study(
    ctx: typer.Context,
    reviewer: Annotated[
        int | None,
        typer.Option(help="Resume this reviewer. Default: resume the last one, or start the next."),
    ] = None,
    new: Annotated[bool, typer.Option("--new", help="Start the next reviewer now.")] = False,
    trial: Annotated[
        bool,
        typer.Option(
            "--trial",
            help="Two records outside the study to learn the screen and keys. Never scored.",
        ),
    ] = False,
    port: Annotated[int, typer.Option()] = 8000,
    browser: Annotated[bool, typer.Option(help="Open the browser.")] = True,
) -> None:
    """Sit someone down and run this. It does the rest.

    Picks the records, puts each in its arm, serves them in order with a practice page at
    the start of each half, times every page, and keeps each reviewer's work in its own
    folder under review/study/. Running it again resumes the same reviewer until they
    finish; after that it starts the next one. Then `sever study report`.
    """
    if ctx.invoked_subcommand is not None:
        return
    import threading
    import webbrowser

    import uvicorn

    from sever.review import study as st
    from sever.review.app import create_app

    if trial:
        typer.echo("preparing the trial: two records, nothing kept or scored...")
        run = st.open_trial()
        number = 0
    else:
        number = reviewer if reviewer is not None else st.pick_reviewer(new=new)
        typer.echo(f"preparing reviewer {number}'s records...")
        run = st.open_run(number)
    if run.finished and not trial:
        typer.echo(
            f"reviewer {number} has finished all {len(run.tasks)} records. "
            f"`sever study --new` starts the next reviewer; `sever study report` updates "
            f"the results."
        )
        return
    chosen = _free_port(port)
    if chosen != port:
        typer.echo(
            f"port {port} is in use (another `sever review` or `sever study` still running?), "
            f"so using {chosen}"
        )
    port = chosen
    url = f"http://127.0.0.1:{port}/"
    typer.echo(
        f"reviewer {number}: {run.completed} of {len(run.tasks)} records done. "
        f"Open {url}  (Ctrl+C to stop; running this again resumes)"
    )
    if browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(run.session, study=run), host="127.0.0.1", port=port, log_level="warning")


@study_app.command("status")
def study_status() -> None:
    """Who has done how much, without building anything."""
    from sever.review import study as st

    numbers = st.enrolled()
    if not numbers:
        typer.echo("nobody has started yet. Run `sever study`.")
        return
    total = st.STUDY_RECORDS + st.PRACTICE_RECORDS
    for n in numbers:
        done = st._completed_positions(st.reviewer_dir(n) / "timings.jsonl")
        typer.echo(f"reviewer {n}: {done} of {total} records timed")


@study_app.command("report")
def study_report(
    out: Annotated[Path, typer.Option(help="The table.")] = Path("results/reviewer.md"),
    data: Annotated[Path, typer.Option(help="The scored pages, committed as evidence.")] = (
        Path("results/reviewer-study.jsonl")
    ),
) -> None:
    """Score every completed page and write the results.

    Writes the scored pages to `results/reviewer-study.jsonl`, which carries reviewer
    numbers and never names, and then builds `results/reviewer.md` from that file alone,
    so the table reproduces from what is committed.
    """
    from sever.eval import reviewer as rv
    from sever.review import study as st

    results = st.collect()
    typer.echo(f"{len(results)} completed pages from {len(st.enrolled())} reviewer(s)")
    st.write_results(results, data)
    path = rv.write_study(rv.read_study(data), out)
    typer.echo(path.read_text(encoding="utf-8"))
    typer.echo(f"wrote {data} and {path}")


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
