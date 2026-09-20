# Plan: Access-to-Information Redaction

**Written:** 2026-09-07. **Status:** building. Started 2026-09-13, about eleven months
ahead of the Aug 2027 slot, because nothing in the portfolio blocks it. Week 1 and most
of week 2 are built and measured; section 12 records every place the build departed
from this plan and why.

**Build:** three weeks, Aug 2 to Aug 22 2027, slack to Aug 31 (the last month of the
twelve). **Package:** `sever`, after the access-law term for redacting part of a record and
releasing the rest. **Fed by:** 04 (the redaction engine `boundary.redact` and the gateway
proxy, both from 04 Part B in May), 03 (the gate runs the evaluation and supplies
intervals and paired comparisons). **Feeds:** nothing in the ten; the corpus generator is
reusable by potential project 15.

> **Employer note, before anything else.** This is a tool the Government of Newfoundland
> and Labrador wants, not one it has built, so there is nothing to reuse and Rule G's reuse
> question does not arise. Open question 05 in the plan repository was closed on
> 2026-09-06 with no concern: the public version is built here, publicly; any internal
> version is built separately on the employer's own tooling with no shared code in either
> direction. Public data only. To keep the distance visible, the real-document test set
> uses published federal releases only, never the employer's own disclosure log, even
> though that log is public too.

---

## 1. What this produces

A tool that reads the records responsive to an access-to-information request, proposes
every redaction with a reason tied to a category of the legislation, keeps what must be
released (the requester's own information, officials acting in their official capacity,
information already public), escalates what it cannot decide, and hands a reviewer a
page-by-page approval workflow with a full audit log, a truly redacted document and the
redaction schedule the requester receives. The tool proposes; a person decides.

The numbers a stranger can check:

| Number | What it shows |
|---|---|
| **Leak rate**: must-redact spans the tool proposed to release, overall and per category, 95% bootstrap CI | The safety number. A leak is a third party's information released |
| **Over-redaction rate**: must-keep spans the tool proposed to redact, overall and per category, with CI | The usefulness number nobody publishes. A tool that blacks out every official's name is a blunt tool |
| Category accuracy: of correctly redacted spans, the share assigned the right category, so the schedule cites the right provision | Whether the reasons are right, not only the boxes |
| Error decomposition: detector misses against decision errors, per category | Whether a leak came from 04's engine not seeing the span or from this tool deciding wrongly |
| Escalation rate and escalation yield: share of spans escalated, and the share of escalations where the reviewer's decision differed from the default proposal | Whether escalation is asking the right questions |
| Over-redaction on real released records: share of visible spans in published federal releases (already judged releasable by a human) that the tool would have redacted | The real-document test, on records a public body actually released |
| Baselines on the same corpus: blunt redact-all-PII, model-only with no rules, rules-only with no model, and span-level decisions without document context | Where the value comes from |
| Decisions made through the gateway on placeholders against decisions on raw text, paired | Whether protecting the personal data from the vendor costs any accuracy |
| Native against scanned documents, with OCR character error rate on the scanned track | Where OCR is the limit |
| PDF leak test: redacted strings recoverable from the output document's text layer or by OCR of its rendering, out of N | A black box over selectable text is not a redaction |
| Reviewer minutes per page with proposals against unaided, small user study, with CI | The time claim |
| Cost per page from the gateway ledger | What it costs to run |

## 2. Design decisions

### 2.1 The taxonomy is written against the legislation and is configurable

Every decision is one of a fixed set of categories, each mapped to a provision of the
federal Access to Information Act and Privacy Act and, as a second configuration, of
Newfoundland and Labrador's Access to Information and Protection of Privacy Act, 2015. The
mapping is a YAML file; adding another jurisdiction is another file. Section references
are verified against the consolidated texts in week 1 and recorded in `docs/taxonomy.md`.

| Code | Decision | Category | Federal anchor (verified week 1) |
|---|---|---|---|
| R1 | Redact | Third-party personal information: identity, contact, identifiers, health, financial, employment, opinions about them | ATIA s.19; Privacy Act s.3 definition |
| R2 | Redact | Personal information of a third party entangled with the requester's (mixed span) | ATIA s.19; severability |
| K1 | Keep | The requester's own personal information | Right of access to one's own information |
| K2 | Keep | Officers and employees of a public body acting in their official capacity: name, title, business contact, work-related opinions and actions | Privacy Act s.3 exceptions |
| K3 | Keep | Information already publicly available | ATIA s.19(2) |
| K4 | Keep | Personal information of an individual deceased more than twenty years | Privacy Act s.3 exceptions |
| K5 | Keep | Consent given, or a discretionary benefit of a financial nature | ATIA s.19(2); Privacy Act s.3 exceptions |
| K6 | Keep | Not personal information at all: organisations, places, dates, generic roles the detector flagged | Definition |
| E1 | Escalate | Role cannot be determined from the record: official or third party | |
| E2 | Escalate | Mixed span the rules cannot sever cleanly | |
| E3 | Flag only | Candidate non-personal exemptions (advice, solicitor-client, law enforcement, third-party business) surfaced for the reviewer, never decided here | ATIA ss.16, 20, 21, 23 as flags |

E3 is deliberate: this tool decides personal-information questions. Other exemptions are a
different judgement and are shown to the reviewer as flags with no proposal.

### 2.2 Rules first, model second, redact-and-escalate when neither is sure

For each span the 04 engine detects, the tool builds a context record: entity type and
text, sentence and block, section heading, document type, author and recipients from
headers and letterhead, signature-block titles, a coreference cluster within the document,
whether the entity matches the configured requester identity, and whether it matches a
public register (published lists of ministers and officials, the document's own
letterhead, the department's published organisation chart). Deterministic rules decide the
clear cases: requester match is K1; a signature block or letterhead role with a title is
K2; a public-register match is K3; a non-personal entity type is K6. The residual goes to a
model with the context record and a constrained JSON schema (category, confidence, the
evidence span it relied on). Below a confidence threshold, or when rules and model
disagree, the proposal is R1 with an escalation flag: the default is to withhold and ask,
never to release and hope. Thresholds are set on the validation split and reported.

### 2.3 Every model call goes through the gateway with the personal data class

Decisions are requested through 04's proxy with `X-Data-Class: personal`. The gateway's
policy for that class redacts personal identifiers to typed placeholders before the request
leaves and rehydrates the answer. The decision layer is designed for this: role, capacity
and requester status are properties of the context, not of the literal name, and the
public-register rule runs locally before anything is sent. The paired ablation in
section 1 measures what, if anything, the placeholders cost. This is the composition
argument in one place: a frontier model used on access-to-information records without
personal data leaving the boundary, measured.

### 2.4 Labels known by construction, real records for the over-redaction test

The main corpus is synthetic by design: public government documents and templates
(complaint correspondence, case notes, email chains, meeting minutes, HR memoranda,
incident reports) populated with generated personas whose roles (requester, third party,
official, deceased, public figure) are assigned before the document is rendered, so every
span's category is known without a human reading it. A model renders the templates into
natural prose through the gateway; a person then hand-verifies every page's labels, which
is the "hand-labelled 200+ pages" in the definition of done and is where the week goes.
Real records enter through published completed federal releases: everything visible in a
released record was judged releasable by a human, so the tool's proposals on those pages
measure over-redaction on real documents. What sits under the existing black boxes cannot
be recovered and is not used.

### 2.5 Redaction is destructive, and a test proves it

The exported PDF removes the text under every approved box (PyMuPDF's redaction
annotations applied), and an optional rasterised export exists for scans. A test extracts
the text layer of every output and OCRs its rendering, and asserts that no redacted string
is recoverable. The count is published. Black boxes drawn over selectable text are the most
common real-world redaction failure, and this project refuses to ship it.

### 2.6 The audit log is append-only and the schedule is generated

Every reviewer action (approve, reject, add, change category, escalate, comment) is a row
in a DuckDB table with who, when, page, span and reason; rows are never edited. The
redaction schedule the requester receives is generated from approved rows: page, extent,
category and provision. The reviewer never edits the schedule by hand.

### 2.7 Out of scope, on purpose

- Deciding non-personal exemptions (advice, legal privilege, law enforcement, third-party
  business). Flagged, not decided.
- Case management, request intake, fee estimates, correspondence with requesters.
- Handwriting recognition. Scanned typed documents only on the OCR track.
- Automatic release. There is no path from proposal to output without a reviewer action
  on every page, and the README says so.
- Any jurisdiction beyond the two configured, except as a documented YAML addition.

## 3. Data

| Source | Size | What it gives | Access and terms |
|---|---|---|---|
| Public government documents and templates (reports, correspondence templates, minutes) from the federal open-government portal | Dozens of templates | The scaffolding for the synthetic corpus | Open Government Licence - Canada; recorded in `docs/data.md` |
| Generated personas and rendered documents (own) | 200+ pages: about 150 native (PDF, DOCX, EML), 50 rendered as scans with noise and skew | Labels known by construction, hand-verified | Written here; no real person |
| Published completed access-to-information releases, federal | 60 to 100 pages sampled across departments | Real records for the over-redaction test | Public; terms of the completed-requests portal read and recorded; employer's own disclosure log excluded by decision |
| Public registers: ministers, deputy heads, published organisation charts | Small | The K3 public-register rule | Public |

Nothing internal. No real personal information beyond what is already public in released
records. Nothing raw is committed; loaders verify checksums; every licence is recorded.

## 4. Architecture

```
sever/
  taxonomy/    categories.yaml (codes, decisions, definitions), federal.yaml and nl.yaml (provision mappings),
               loader.py, render_docs.py (writes docs/taxonomy.md from the YAML)
  corpus/      personas.py (roles assigned first), templates/ (six document types), generate.py (render through
               the gateway), render.py (PDF, DOCX, EML), scan.py (rasterise, noise, skew), labels.py,
               verify.py (hand-verification tool, page by page), releases.py (federal releases, visible-span labels)
  ingest/      pdf.py (PyMuPDF), docx.py, eml.py, ocr.py (Tesseract, CER measured on the scan track),
               layout.py (blocks, headings, letterhead, signature blocks, tables), document.py (pages, spans)
  detect/      engine.py (boundary.redact analyzer plus recognisers: case and file numbers, employee ids),
               coref.py (within-document clusters)
  context/     roles.py (authors, recipients, titles), requester.py (configured identity match),
               register.py (public officials and letterhead), record.py (the context record)
  decide/      rules.py, model.py (constrained JSON through the gateway proxy, class personal, prompt caching),
               thresholds.py, pipeline.py (rules, model, redact-and-escalate), explain.py (reason text per span)
  review/      app/ (FastAPI plus htmx: page image, overlays, approve, reject, add, escalations queue),
               audit.py (DuckDB append-only), export.py (true redaction PDF, rasterised option, schedule)
  eval/        confusion.py (per category, bootstrap CIs), decomposition.py (detector against decision),
               baselines.py (blunt, model-only, rules-only, sentence-only), releases_eval.py (over-redaction
               on real records), placeholders_eval.py (paired), pdf_leak.py, timing.py (reviewer study),
               gate/ (eval spec and item loader for the 03 gate)
  cli.py       sever corpus build | verify | ingest | propose | review | export | eval | report
docs/          taxonomy.md, data.md, escalation.md (where the tool declines to decide), reviewer-study.md
```

### Tests that matter

The PDF leak test (2.5); a requester's span is never proposed as R1 under any rule path;
the audit table refuses updates and deletes; taxonomy YAML validates (every code mapped in
both jurisdictions or explicitly marked unmapped); rules fixtures per category, including
the traps (an official named as a complainant, a requester also mentioned as a witness, a
deceased person with a date); OCR-track grading tolerates character-level noise within the
measured error rate; the gateway request never contains a raw detected entity (asserted
against the proxy's request log in tests).

## 5. Week by week

| Dates | Built | Done when |
|---|---|---|
| Aug 2 to 8 | Taxonomy YAML and `docs/taxonomy.md` with provisions verified; personas and templates; corpus generation through the gateway, native and scan tracks; federal releases sampled with terms recorded; ingestion and layout; hand-verification tool; verification begins; gate eval spec | Corpus v1: 200+ pages, labels, checksums committed; verification half done |
| Aug 9 to 15 | Detection on the 04 engine plus recognisers; coreference; context record; rules; model decisions through the proxy with class `personal`; thresholds on validation; escalation; all four baselines; error decomposition; placeholders ablation; verification finished | First results table with CIs through the gate; `docs/escalation.md` drafted |
| Aug 16 to 22 | Reviewer app; audit log; true-redaction export and schedule; PDF leak test; reviewer study (four reviewers, twenty pages each, with and without proposals); over-redaction on real releases; hosted demo on the shared VPS with synthetic documents only; Rule C write-up; README; `v0.1.0` | Every table in section 1 filled; demo at redaction.peterparker.ca; repository public |
| Aug 23 to 31 | Slack, and the end of the twelve months | |

First to drop if behind: the scan track reduced to twenty pages; the sentence-only baseline;
the reviewer study reduced to three reviewers. The taxonomy, the corpus, the leak and
over-redaction numbers, the real-release test, the reviewer workflow with audit log and
schedule, the PDF leak test and the blunt baseline are not droppable.

## 6. Cost

Prices as of 2026-09-07 (Anthropic list per million tokens: Haiku 4.5 at $1 in and $5 out,
Sonnet 5 at $2 in and $10 out; cache reads at a tenth of input). OCR, layout, detection and
the reviewer app run locally.

| Item | Basis | US$ | CA$ |
|---|---|---:|---:|
| Corpus generation | 200 pages, about 900 output tokens each, mid-tier model | 3 | 4 |
| Decision layer, primary model | About 30 candidate spans per page, half resolved by rules, 3,000 model decisions per full run at about 1,500 tokens in (page context cached per page) and 80 out; six full runs across configurations and thresholds | 12 | 16 |
| Decision layer, mid-tier ablation on a 50-page subset | | 6 | 8 |
| Model-only baseline | One full run, no rules, more decisions | 6 | 8 |
| Placeholders against raw text ablation | One paired run | 4 | 5 |
| Hosted demo, Aug 2027 | Shared VPS, no new line; demo traffic capped | 3 | 4 |
| **Total** | | **34** | **45** |

About CA$45 of the CA$55 line. The remainder buys a second run of the reviewer study or a
larger real-release sample. If the primary model's leak rate is not acceptable, the
mid-tier model becomes primary and the cost roughly doubles; that decision goes to STATUS.
Actuals go in the plan repository's STATUS next to the estimate.

## 7. Handover

Last project in the sequence; nothing in the ten imports `sever`. What carries forward:
the corpus generator with roles-first personas, reusable by potential project 15; the
taxonomy YAML pattern; and the strongest single demonstration of the 04 gateway's
purpose, cited from 04's README. `v0.1.0` at Aug 22 2027.

## 8. Risks

| Risk | Handling |
|---|---|
| Legal nuance varies by jurisdiction and the mapping is wrong somewhere | Provisions verified against consolidated texts in week 1; the taxonomy is a proposal a reviewer applies, not a legal determination; the README says so in the first screen; configurable per jurisdiction |
| Labelling time | Labels are known by construction; the human work is verification, not annotation; 200 pages at a few minutes each is one week of evenings |
| OCR quality on scans | Reported separately with the measured character error rate; the scan track is the first thing to shrink |
| Over-trust in the proposals | Approval is explicit per page; over-redaction and leak rates are on the README's first screen; there is no path to output without reviewer actions |
| Synthetic documents are too easy | Templates include the traps (officials as complainants, requesters as witnesses, mixed spans); the real-release test is the check on realism for the keep side |
| The model-only baseline wins | Published either way; if the rules add nothing, the plan says so and the decision layer becomes model-first with rules as guards |
| Vendor sees personal information | It does not: class `personal` through the gateway placeholders identifiers before the request leaves; a test asserts it |
| 04 Part B slips | The engine and proxy are due May 23; if the proxy is late, the decision layer calls the library directly with the same redaction module, and the placeholders ablation still runs |
| Perception at work | Two toolchains, nothing crossing; federal releases only; employer's own log excluded |
| End of the twelve months | Slack is the last week of August; the project is built so the first two weeks alone produce the results table |

## 9. Rule C candidates

1. **Blunt redact-all-PII.** Every span the detector finds is redacted. Expected: leak rate
   near zero and an over-redaction rate that removes most officials' names from records
   the government actually released; the over-redaction figure on the real-release set is
   the evidence.
2. **Model-only decisions with no rules.** Expected: more leaks on requester-versus-third
   party confusions and role ambiguity, higher cost per page, and lower consistency across
   mentions of the same person; measured on the same corpus.
3. **Deciding each span from its sentence alone, without the document context record.**
   Expected: officials in correspondence become third parties, because the title lives in
   the signature block and not in the sentence.

Whichever produces the clearest evidence becomes `docs/rejected.md`.

## 10. Definition of done

- [ ] Taxonomy written against the federal acts and one provincial act, provisions verified, published as YAML and `docs/taxonomy.md`
- [ ] Labelled corpus of 200+ pages with per-span categories, hand-verified, checksums committed; native and scanned tracks
- [ ] Leak rate and over-redaction rate per category with bootstrap CIs, on the README's first screen
- [ ] Category accuracy and error decomposition reported
- [ ] Blunt, model-only, rules-only and sentence-only baselines on the same corpus
- [ ] Over-redaction measured on published federal releases
- [ ] All model decisions through the 04 gateway with class `personal`; placeholders against raw text ablation reported
- [ ] Reviewer workflow with append-only audit log, true-redaction export and generated schedule
- [ ] PDF leak test published, out of N
- [ ] Reviewer minutes per page with and without proposals, with CI
- [ ] `docs/escalation.md`: where the tool declines to decide, and why
- [ ] Cost per page from the gateway ledger
- [ ] Hosted demo with synthetic documents at redaction.peterparker.ca
- [ ] One rejected approach documented with evidence (Rule C)
- [ ] Repository public, `v0.1.0` tagged

## 11. Deferred

| Deferred | Kept so the door stays open |
|---|---|
| Non-personal exemptions decided, not only flagged | E3 flags already carry the provision; a second decision layer would consume the same context record |
| Further jurisdictions (Ontario, British Columbia, Alberta) | One YAML file each |
| Handwriting on scans | The OCR module is a single interface; a handwriting engine would slot in behind it |
| Consultation workflow with third parties (notice and representations) | The schedule already identifies third-party spans by category |
| Learning from reviewer decisions | The audit log has every reviewer correction; training on it is a data question for later, with consent and jurisdiction rules first |
| A French-language track | Templates and personas are language-parameterised; the detector's French recognisers are the missing piece |

---

## 12. Amendments from the build

Written 2026-09-13, the first build day. This plan is not edited in place: what turned out
differently is recorded here, with the reason, so the plan and the code can be read against
each other.

### 12.1 The build started eleven months early

The Aug 2027 slot was chosen because this project is fed by 04 and 03. Neither blocks the
parts built here, and the portfolio has been running ahead across the board, so the work
started on 2026-09-13. Nothing else in the sequence moves.

### 12.2 04 Part B does not exist, so this project owns a detector and a placeholder policy

The plan has detection coming from `boundary.redact` and substitution from the gateway's
policy for data class `personal`, both due in 04 Part B in May 2027. Section 8 anticipated
the **proxy** slipping and said the decision layer would "call the library directly with
the same redaction module". That contingency does not apply: `boundary` v0.2.0 has
`Gateway`, `ChatRequest` and the ledger, and no redaction module at all. There is no
library to call.

So `sever` owns both, behind seams:

- `sever.detect.types.Detector` is a protocol, and `SeverDetector` implements it on the
  same stack the plan named (Presidio plus spaCy) with recognisers for the identifiers a
  general engine does not know. When 04 Part B lands, a `BoundaryDetector` implements the
  same protocol and nothing downstream changes.
- `sever.decide.placeholders` performs the substitution locally and the request still goes
  through `boundary.Gateway` with the data class recorded on the call. When the gateway's
  policy exists, this module becomes the fallback and the guard stays where it is.

The paired placeholders-against-raw-text ablation is unaffected: it compares two payloads,
and which component builds them does not change what it measures.

### 12.3 A second, detector-independent scrub was added to the outbound boundary

Not in the plan, and the plan was wrong to omit it. Section 2.3 assumed that substituting
detected entities was sufficient to keep personal information inside the boundary. The
corpus-wide test found 74 real values leaving it, from three causes, the third of which is
structural: **Presidio's recall is not 100 percent, and a boundary built on detections
inherits every miss.**

`sever.decide.placeholders.scrub_unrecognised` now masks anything proper-noun-shaped or
identifier-shaped that survives substitution, unless it is on a list of terms that carry
decision-relevant meaning and identify nobody. The full account is in `docs/rejected.md`.
This costs the model context and therefore accuracy, and the ablation in section 1 measures
that cost; the alternative costs a name.

### 12.4 The PDF leak test asks a different question than section 2.5 specified

Section 2.5 says the test "asserts that no redacted string is recoverable" from the text
layer or an OCR of the rendering. Implemented literally, that test is wrong in both
directions. It over-reports: on the first run it flagged ten leaks, all of them the word
"Minister" appearing correctly in an unredacted heading elsewhere on the page. And it
under-reports, because a name that survives inside a box but is split across a line by the
extractor does not match a substring test.

The test now extracts the text clipped to **each applied rectangle** and asserts it is
empty, which is what a redaction actually claims to have done and is checkable exactly. The
export returns the rectangles it applied so the checker can do this. A companion test builds
a deliberately broken export, a filled rectangle drawn over live text, and asserts the
checker catches it.

### 12.5 The audit log's immutability rests on a hash chain, not on the database

Section 2.6 says rows are never edited. The first implementation added DuckDB rules to
refuse UPDATE and DELETE. DuckDB has neither rules nor triggers, the statements were parser
errors, and the code swallowed them and set a `rules_enforced` flag that was always false
and read like a guarantee. That is worse than no defence and it is gone.

Immutability now rests on two things that are real: the module exposes no method that can
change a row, and every row carries a hash chained to its predecessor, so a row that is
changed, removed or reordered breaks the chain and `verify_chain` says which one. The
audit log also stores a sha256 of the severed text rather than the text, so the log of what
was withheld does not itself contain the personal information.

### 12.6 An official's employee number is R1, not K2

A judgement the plan's table did not reach. The Privacy Act exclusion for officials covers
information that "relates to the position or functions", and its examples are the title,
the business address and telephone number, the classification and the salary range. A
payroll identifier is an identifying number assigned to the individual, which is the
definition's own paragraph (c), and releasing bodies redact them in practice. This moves
the K2 column, so it is written down in `sever/corpus/personas.py` where it can be argued
with rather than discovered in a confusion matrix.

For the same reason, an organisation name is K6 for every persona rather than K2 for an
official's employer: a department is an institution, not a person.

### 12.7 The corpus is 210 single-page documents

The plan says 200-plus pages across six document types, roughly 150 native and 50 scanned.
The native track is built: 210 documents, one page each, 5,355 labelled spans, six
templates cycled with a fresh cast per document. Persona names are unique within a document
and repeat across the corpus, which is both necessary (a pool of 32 forenames and 32
surnames cannot make 1,000 unique casts) and right (a real disclosure package names the
same officials repeatedly, and a corpus that invents fresh people every time would be
testing an easier problem).

Multi-page documents and the scanned track are not built. Section 5 named the scan track as
the first thing to drop if behind; it is not dropped, it is not yet started.

### 12.8 Provision verification is partial, and the format makes that visible

Section 2.1 says provisions are "verified against the consolidated texts in week 1". 18 of
33 are. The federal mapping is 13 of 18; the Newfoundland and Labrador mapping is 5 of 15,
and the largest gap is the paragraph letters inside ATIPPA section 40(2), which is the
exception K2 rests on and therefore the code the whole over-redaction number turns on.

Rather than leave this as an omission, the taxonomy format refuses a provision that is
neither verified (quote, date read, URL read from) nor explicitly marked unverified with a
reason. `docs/taxonomy.md` prints the count at the top. Nothing defaults to verified.

### 12.9 The model layer has been run, and the threshold was the finding

2026-09-20. Caps were entered in 04's `caps.yaml` (US$50 monthly, US$12 per run) and
confirmed, and the model layer ran against Haiku 4.5 over the full 210-document corpus
through `boundary.Gateway` with data class `personal`. Section 2.3's property held: the
corpus-wide test asserts no persona value reaches a request, and the run itself sent none.

Three things the plan did not anticipate.

**The confidence threshold was the wrong number and the sweep that found it was nearly
unaffordable.** Section 2.4 fixed 0.7 and section 9 promised to set it on a validation
split. Swept, 0.7 turns out to change nothing: a third of the model's answers are discarded
at that setting and not one published figure moves, because the discarded answers are the
ones where the model itself answered E1. The real boundary is 0.90, where the leak rate
falls from 13.4 percent to 7.9 and over-redaction rises from 15.6 to 22.7, and above it
nothing moves again. The full account is entry 3 of `docs/rejected.md`.

A sweep is only honest if every row scores the *same* model answers, so the decider records
each reply to `results/model-answers.jsonl` and replays it. That was not in the plan and it
is what made the sweep cost nothing: one paid run of US$0.51 bought all eight rows, and
`--replay-only` reproduces the model row of the published table from a clone with no
gateway, no key and no spend. The plan assumed the model numbers would be the part of this
repository a stranger could not check. They are not.

**The spend was two orders of magnitude below the estimate.** Section 6 budgeted CA$55 and
this project told 04 to expect about US$5.70 a full run. The measured figure is US$0.51,
because the corpus is template-generated and after placeholder substitution 2,084 of the
2,550 requests in a run are byte-identical to one already made. Total spend across the
smoke runs, the 60-document run and the full run is about US$1.10.

**Running the model exposed a detector bug that a corpus evaluation could not see.** The
case-number recogniser matched the heading "CASE NOTES" and proposed "NOTES" as a case
number. Recall cannot see a false entity over ordinary prose, and this one was found by
reading six proposals on the first live call. `tests/test_recognisers.py` did not exist
before this; it does now, and it holds both label-word bugs as fixtures.

Still outstanding from the definition of done in section 10: the placeholders ablation and
the cost per page; the model-only baseline (rules-only, sentence-only and blunt are
measured); the scanned track and its character error rate; the published-federal-releases
track; the reviewer web app and the reviewer time study; the hosted demo.

### 12.10 The corpus was easier than the province, and an outside report is what showed it

2026-09-20. Section 3 specifies personas whose names are "plausible for Newfoundland and
Labrador". They were, and they were also, every one of them, plain ASCII: no apostrophe, no
Mac or Mc prefix, no accented letter, no hyphen, no two-token surname. In 5,355 labelled
spans there was not one O'Brien and not one MacDonald, in a province where both are
ordinary. That was not a decision anyone took; it was the shape of a hand-written list
nobody re-read.

It could not be found from inside. Every test passed, on a corpus that could not fail them.

It was found because project 04 fixed the same blindness in their own second pass and said
so, adding that re-running this project's evaluation would not show the difference because
the corpus is ASCII. It did not: `boundary.redact` 0.5.4 measures identically to 0.5.1
here, to the decimal, across every entity type. A benchmark that cannot see a real bug
being fixed cannot see one being introduced.

Three things came out of following it up, and two of them were defects in this project
rather than in the corpus.

**The detector-independent scrub had exactly the bug 04 had just fixed.** `docs/rejected.md`
entry 2 argues that a privacy boundary whose strength equals a detector's recall is not a
boundary, and `scrub_unrecognised` is what that argument rests on. Its pattern was
`[A-Z][a-z]{2,}...`, which is ASCII: an accented forename and a Mac surname passed
through it completely untouched, and O'Brien came out as "O'" plus a mask. The backstop
was not a backstop for anyone whose name has an accent or an apostrophe. Rewritten with
Unicode-aware token matching and a `_is_name_shaped` predicate in Python rather than a
character class; `tests/test_scrub_shapes.py` holds the shapes.

**The outbound guard refused ordinary English.** A document-wide policy licenses the parts
of a name, so the surname Le Drew put "drew" on the guarded list, and the guard's substring
test found it inside "withdrew". A minute recording that a delegation withdrew would not
send. Fail-closed, so it cost a run rather than a person, and it is still a defect: a guard
that refuses ordinary words trains whoever maintains it to route around it. Now a
whole-word match, which loses nothing, because an occurrence that is the name is a whole
word and one that is a fragment is not.

**One thing was a corpus bug rather than a result.** Addresses were built by lowercasing
the name, so an accented surname produced an address carrying the accent and a two-token
surname produced an invalid double dot. Real directories transliterate. Fixed, which also
makes the harder question askable: when the page says an accented name and the address says
the transliteration, a policy keyed on the exact surface form ships the surname inside the
address. The persona ground-truth test normalises accents before it looks, and it now runs
on the hard profile too.

`NameProfile` is the deliberate form of the amendment: `plain` is the published corpus and
every committed number stays measured on it, `nl` is the harder one, and `sever eval-names`
prints both. On `nl`, person recall falls from 96.2 to 93.4 percent for this project's
detector and from 96.5 to 94.2 for 04's. The published tables did not move, and neither did
a single model request: the full 210-document replay hit the answer cache with no misses,
because the plain corpus contains none of the shapes the fix addresses. That is the finding
restated as a measurement.

Whether `nl` should become the default is not settled here. It should be argued on what a
released record actually looks like, not on which number is more flattering, and the
argument is easier to have now that both numbers exist.

### 12.11 The name-shape loss is lexical, not orthographic, and the fix is already half built

2026-09-20, following 04's question: which of apostrophes, Mac prefixes and accents
dominates the drop, since the answer decides whether the next move is a recogniser or a
better model. A mixed pool cannot answer it, so there is now one corpus per shape, varying
the surname alone with the forenames held plain. Person recall, against the plain corpus:

| shape | sever | boundary.redact |
|---|---|---|
| apostrophe (O'Brien) | -0.7 | **0.0** |
| Mac and Mc | -0.4 | **0.0** |
| hyphenated | +0.6 | +0.7 |
| accented surname | -0.9 | -1.0 |
| **two-token surname** (St. Croix, Le Drew) | **-6.4** | **-4.5** |
| **bare accented forename** | **-7.4** | **-7.0** |

**None of the three shapes in the question dominates.** Apostrophes and Mac prefixes cost
04's engine nothing measurable. The two expensive shapes are a two-token surname and an
accented forename, and the asymmetry between an accented forename at 7.4 points and an
accented surname at 0.9 is the clue: the same character class costs eight times more in one
position than the other.

The probes in `tests/test_name_shapes_detected.py` say why. Every shape is found in
ordinary prose with a forename beside it, in a signature block and in a distribution list.
What is missed is an unfamiliar token **standing alone**: a bare surname in a "Present:"
list or a signature block, a bare accented forename in prose. One preceding honorific
rescues all of them.

So this is lexical coverage, not character handling. The first-pass model has learned the
common names and not the uncommon ones, and it fails exactly where there is no neighbouring
evidence for any model to use. A second pass that fixes character classes cannot reach it,
and neither can a larger model, because the information is not in the sentence. A gazetteer
can, and so can a cheaper thing this project already has.

**The fix is half built.** `PlaceholderPolicy.for_detections` already takes a detected
"Bernadette Le Drew" and registers "bernadette" and "drew" as aliases, because the outbound
boundary had this exact problem and solved it: a detected full name licenses its parts. The
detector does not use the same information. A document-wide sweep that, for every person
detected anywhere in a record, finds the other occurrences of their name parts, recovers
precisely the misses above, and needs no model and no gazetteer.

### 12.12 The sweep is built, and it cost almost nothing to run

2026-09-20, authorised the same day. `sever.detect.sweep` runs after the per-page detectors
and, for every person they found anywhere in the document, claims the other whole-word
occurrences of that person's name parts across the whole record. Case-sensitive, whole-word,
never over an existing detection, and vocabulary words are refused so that a heading typed
as a PERSON does not put a box over the same word on every page. On by default, and
switchable, because the point of the exercise was to measure it.

Person recall, the same detector over the same corpora with the sweep off and on:

| name profile | off | on |
|---|---|---|
| plain (the published corpus) | 96.2% | **98.8%** |
| nl (all five shapes) | 93.4% | **98.0%** |
| two-token surname | 89.8% | **96.6%** |
| bare accented forename | 88.8% | **96.8%** |

The prediction in 12.11 was that the loss is lexical and the document holds the evidence.
It does: the two shapes that cost the most gain the most, 6.8 and 8.0 points, and **the
penalty for using this province's names falls from 2.8 points to 0.8.**

On the published corpus the effect is smaller and still real. Detector recall 97.4 to
**98.6 percent**, detector misses 25 to 16, leak rate 5.4 to **4.7** with the rules alone
and 7.9 to **7.2** with the model. Over-redaction rises 0.4 of a point, which is the
expected direction: a recovered name with no title attached escalates, and an escalation
withholds. Fewer leaks for slightly more reviewer time is the trade this project says it
wants, and here it is bought rather than argued.

The paid re-run cost **US$0.027**. The answer cache was expected to be invalidated wholesale
and was not: 2,550 of 2,574 requests replayed unchanged, because the spans the sweep adds
are name parts of people the rules already place, so they are decided without a model call
and the sentences around them were already substituted. The estimate given before the work
was US$0.5, which was wrong by a factor of twenty in the cheap direction.

One limitation, stated because it bounds the claim: the sweep needs the person to be found
**somewhere**. A record that never names someone in a position the model can read gets
nothing from it. That is the residual a gazetteer would cover and this does not, and it is
now a number rather than a caveat: **23 of the 29 person spans still missed, 79 percent,
belong to someone the detector never found as a person anywhere in that record.**
`DetectorReport.unseen_people` computes it and `results/detectors.md` prints it.

Getting that number right took two attempts and the first was wrong in the flattering
direction. It counted a persona as seen when *any* span of theirs was found, including
their email address, and reported that 0 percent of the remaining misses were out of
reach, which would have meant the sweep could in principle recover all of them. An email
address licenses nothing for a name sweep: it seeds from detected person spans and from
nothing else. Restricting the test to person spans moved the figure from 0 to 79 percent
and reversed the conclusion. It was caught because 0 percent looked too good and got a
second reading, which is not a reliable way to catch anything.

### 12.13 Labrador, and the leak the sweep found on its way past

2026-09-20. Project 04 asked twice about caseless scripts, and the answer needed to stop
being a reassurance. Labrador Inuttitut in these records is written in Latin script, not
the syllabics used in Nunavut, so the alphabet is not this jurisdiction's problem. The
problem is vocabulary, and `NameProfile.LABRADOR` is the profile that says so: Innu
surnames from Sheshatshiu and Natuashish and Inuit surnames from the Nunatsiavut
communities, every one of them plain ASCII with no accent, no apostrophe and no internal
capital. Orthographically they are Doucette. To a model trained on English news they are
nothing, and that is the whole of the effect the five shape profiles were measuring.

Building it found something worse than a recall gap, and it is the more important half of
this amendment.

**A name the detector calls a place is released, and recall cannot see it.** Presidio types
"Bernadette Tuglavina" as a PERSON in the sentence that introduces her and the bare
"Tuglavina" in the distribution list below as a **LOCATION**. The span is found, so recall
counts it and every number in `results/names.md` looks fine. What happens next is that
`not_personal_information` fires on a LOCATION, returns K6, and K6 releases. A third
party's surname goes into the released record with "not information about an identifiable
individual" printed beside it in the schedule, which is a leak and a false statement about
why.

This is the same failure as the minister typed as a LOCATION in 12.x, and the guard added
then does not reach it: that guard yields to a register match or a paired title, and a
third party in a distribution list has neither.

`sweep.retype_known_people` fixes it from the same evidence the sweep already uses. Where a
span is **exactly** a name part the document has attributed to a person elsewhere, and its
current type is one that releases, it is re-typed as a person. Exactly, and nothing looser:
"Hearn" inside "Hearn Building" is a place doing honest work, and re-typing the building
would black out somewhere the requester is entitled to see.

The general lesson is the one this project keeps relearning from a different direction. A
recall number cannot see a span that was found and mislabelled, and mislabelling toward a
category that releases is worse than missing the span, because a miss at least leaves the
blunt baseline's behaviour intact while a wrong label produces a confident, reasoned,
wrong release.
