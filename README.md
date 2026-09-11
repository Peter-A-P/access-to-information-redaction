# Access-to-Information Redaction

An access-to-information request means staff reading hundreds of pages and deciding, line
by line, which personal information must be withheld and which must be released. Blunt
PII tools redact all of it and are useless, so it is done by hand. This tool proposes every
redaction with a reason tied to a category of the legislation, lets a reviewer approve or
reject page by page with a full audit log, and publishes how often it redacts what must go
and how often it keeps what must stay. Days of reading become hours of review.

**Status: planning.** Nothing has run yet. The plan is in [PLAN.md](PLAN.md): a three-week
build in August 2027 on the portfolio's redaction engine and gateway, measured with the
AI Release Gate.

**The tool proposes; a person decides.** There is no path from a proposal to a released
document without a reviewer action on every page.

## Result

Not yet measured. The build fills these tables.

**On the labelled corpus (200+ pages, native and scanned)**

| Category | Leak rate (must-redact released, 95% CI) | Over-redaction rate (must-keep withheld, 95% CI) | Category accuracy | Escalation rate |
|---|---|---|---|---|
| _not yet_ | | | | |

**Against the baselines, and on real records**

| System | Leak rate | Over-redaction rate | Over-redaction on published federal releases | Cost per page |
|---|---|---|---|---|
| This tool (rules, then model through the gateway) | _not yet_ | | | |
| Blunt redact-all-PII | | | | |
| Model only, no rules | | | | |
| Rules only, no model | | | | |

| PDF leak test | Reviewer minutes per page, with vs without proposals (95% CI) | Decisions on placeholders vs raw text (paired delta) |
|---|---|---|
| _not yet_ | | |

## What this does not do

- It does not decide non-personal exemptions (advice, legal privilege, law enforcement,
  third-party business). It flags candidates for the reviewer with the provision and
  makes no proposal.
- It does not release anything. Every page needs a reviewer's explicit action.
- It is not legal advice. The taxonomy maps categories to provisions of two acts and is
  configurable; a public body applies its own interpretation.
- It does not read handwriting. Scanned typed documents only.

## How it works

See [PLAN.md](PLAN.md). Documents are ingested with layout (headings, letterhead, signature
blocks, tables); scans go through OCR with the error rate measured. The portfolio's
redaction engine detects candidate spans. For each span a context record is built: who is
speaking, in what role, whether the information is the requester's own, whether it is
already public. Deterministic rules decide the clear cases; a model decides the residual
through the Compliant AI Gateway with the personal data class, so the vendor sees
placeholders, never names; when neither is sure the proposal is to withhold and escalate.
A reviewer approves page by page in a small web app; every action is an append-only audit
row; the export removes the text under every box (a test proves nothing is recoverable)
and generates the redaction schedule. The evaluation corpus is synthetic with labels known
by construction and hand-verified, plus published federal releases as the test of
over-redaction on real records.

## Part of a portfolio

One of fifteen projects built over twelve months. It is built on the Compliant AI Gateway's
redaction engine and proxy and measured with the AI Release Gate. It is the clearest
demonstration of what the gateway is for: a frontier model used on
access-to-information records without personal data leaving the boundary, measured.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's, including eight
years inside a public body that answers access-to-information requests. AI coding
assistants (Claude Code) were used for implementation and drafting, the way a senior
engineer uses them in 2026. Every number in the results tables is reproducible from this
repository with one command, and that reproducibility is the evidence that matters.
