# Working notes for Claude Code

This repository is Hundreds of Pages, Redacted in an Afternoon, package `sever`: context-dependent
redaction proposals for access-to-information requests, with an exemption taxonomy
mapped to public legislation, a rules-then-model decision layer through the portfolio
gateway, a reviewer workflow with an append-only audit log, and true-redaction output.
Built August 2027. The plan is in [PLAN.md](PLAN.md).

## Read first

- [README.md](README.md): what this is and the current result tables.
- [PLAN.md](PLAN.md): the design. Do not deviate from it silently; if something in it turns
  out wrong, change the plan in the same commit as the code and say why in the commit
  message.
- `docs/taxonomy.md`: the categories and their provisions, generated from
  the YAML, never hand-edited.

## Engineering standard

- Python 3.13. Typed throughout; `mypy --strict` and `ruff` clean in CI.
- Tests that fail meaningfully: the PDF leak test, the requester-never-third-party test,
  the audit-log immutability test, the rules fixtures with the traps, the gateway-request
  test that asserts no raw entity leaves.
- `pyproject.toml` with pinned major versions and a comment saying why for each pin.
- Docs ship in the same commit as the change.
- Never commit credentials, or anything from `.env`.

## Rules specific to this repository

- **Public data only.** Synthetic personas and public documents; published federal releases
  for the real-record test. Never the employer's own disclosure log, never any internal
  document, template, feature or threshold. If a design starts to resemble an employer
  system, stop and raise it.
- **The tool proposes; a person decides.** No code path produces a released document
  without a reviewer action on every page.
- **Withhold and escalate when unsure.** The default for an undecided span is redaction
  with an escalation flag, never release.
- **Every model call goes through the 04 gateway with class `personal`.** A test asserts
  that no raw detected entity appears in an outbound request.
- **Redaction is destructive.** Exports remove text under boxes; the leak test runs on every
  export in CI.
- **The audit log is append-only.** Reviewer actions are rows, never edits.
- **The taxonomy is YAML.** Categories and provisions live in `taxonomy/`; the Markdown is
  generated.
- **Every reported number carries a confidence interval** and says which track (native,
  scanned, real releases) it came from.
- **Plain punctuation** in everything written here: no em-dashes or other typographic
  dashes, straight quotes only.

## What goes in the README

The README opens with the one-liner, the "proposes, a person decides" line, the results
tables and the honest limitation, before any installation instructions. The report command
fills the tables; do not hand-edit them. Record one approach that was tried and rejected,
with the evidence, once the work has produced it.
