# Plan: Hundreds of Pages, Redacted in an Afternoon

**Written:** 2026-09-07. **Status:** building. Started 2026-09-13, about eleven months
ahead of the Aug 2027 slot, because nothing in the portfolio blocks it. As of 2026-10-01
everything in section 10 is built; what is not yet measured is the reviewer study (waiting
for people), the real-release track (waiting for downloaded packages) and the hosted demo.
Section 12 records every place the build departed from this plan and why.

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
               gate/ (eval spec and side files for the 03 gate; see 12.30)
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

Ticked as of 2026-09-20. A box is ticked only when the thing it names is measured and
published, not when the code for it exists.

- [x] Taxonomy written against the federal acts and one provincial act, provisions verified, published as YAML and `docs/taxonomy.md`
- [x] Labelled corpus of 200+ pages with per-span categories, hand-verified, checksums committed; native and scanned tracks
- [x] Leak rate and over-redaction rate per category with bootstrap CIs, on the README's first screen
- [x] Category accuracy and error decomposition reported
- [x] Blunt, model-only, rules-only and sentence-only baselines on the same corpus
- [ ] Over-redaction measured on published federal releases
- [x] All model decisions through the 04 gateway with class `personal`; placeholders against raw text ablation reported
- [x] Reviewer workflow with append-only audit log, true-redaction export and generated schedule
- [x] PDF leak test published, out of N
- [ ] Reviewer minutes per page with and without proposals, with CI
      (`sever study` runs the whole study and `sever study report` scores it; see 12.29.
      Nobody has sat down yet)
- [x] `docs/escalation.md`: where the tool declines to decide, and why
- [x] Cost per page from the gateway ledger
- [ ] Hosted demo with synthetic documents at redaction.peterparker.ca
- [x] One rejected approach documented with evidence (Rule C)
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
track; the reviewer web app and the reviewer time study; the hosted demo. (The ablation and
the cost per page have since landed; section 10's boxes are the current list.)

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

### 12.14 The placeholders ablation ran, and the premise was backwards

2026-09-20. Section 1 asks what the privacy boundary costs in accuracy, and `docs/rejected.md`
entry 2 answered the question before measuring it: over-masking costs the model context and
therefore accuracy, and the ablation would price that cost. The ablation has now run and
there is no cost to price. Taking the names away **halved the leak rate**, from 60.2 percent
to 30.1, while raising over-redaction from 7.4 to 19.0.

The mechanism is visible in the escalation column. Shown a plausible name the model's
escalation rate falls from 30.5 percent to 14.1: it becomes willing to place the person. It
is then wrong about which side of the line they are on more often than not, and the two arms
agree on only 55.7 percent of the spans they were both asked. The name is doing a great deal
of work in the model's reasoning and the work is harmful. Deprived of it the model has only
the structure to reason from, which is the evidence that actually decides the question, and
when the structure does not settle it the model says so.

So the sentence this project has been repeating, that the boundary costs accuracy and is
worth paying for anyway, was a concession that did not need making.

**A design decision inside the measurement, which matters more than the measurement.** The
raw arm sends names. Running it through a vendor would break the rule in CLAUDE.md, the
guard in `PlaceholderPolicy`, and the corpus-wide test, and the personas being invented does
not rescue it: what this project sells is that the pipeline *cannot* send a name, not that
the names it sends do not matter. So both arms run on a model on this machine, and
`assert_loopback` refuses to construct the raw decider unless the provider is price-zero,
declares single-region residency, and answers on a loopback host. All three are required and
each is tested alone; the case worth having is a billing host reachable on loopback, which a
URL check alone would wave through.

Two consequences. The honest one: both arms run on a 7B model, so they leak far more than
the pipeline does on Haiku and these absolute numbers are not the pipeline's. The pairing
supports the direction and the rough size, on 20 documents, with the intervals printed. The
good one: this is the only part of the model layer a stranger can reproduce with no key, no
vendor account and no spend.

One incidental observation, recorded because it is a privacy property rather than a
performance one. Asked about the same 244 spans, the placeholder arm needed 171 distinct
requests and the raw arm needed 239: 30 percent of the masked payloads repeated, against 2
percent of the raw ones. Placeholder payloads repeat across documents because the structure
repeats once the names are gone; raw payloads are unique because the names are. A redacted
corpus is more cacheable than an unredacted one, which is a small argument for the boundary
that has nothing to do with privacy at all.

It is a reported column rather than a remark, in `Ablation.to_markdown`, and it is per arm
rather than blended, because a blended hit rate would average the effect away. 04 made the
same change to their Part B cache measurement on the strength of this number, which is the
right instinct: the finding is the gap between the arms, so a measurement that cannot show
two arms cannot show the finding.

**The heading was asserting the conclusion.** 04, amending their own plan after this result,
noticed that their results table said "Quality cost of redaction" and that a column heading
phrased that way decides the question before the run does. The same sentence was at the top
of this file's output: `results/placeholders.md` was titled "What the privacy boundary costs
in accuracy", which is a heading only the losing hypothesis can sit under. It reads "does to"
now, in the generated file, the module, the command and the README's link. The numbers did
not change and nothing about the measurement changed; what changed is that the table no
longer tells the reader what to find in it. Worth watching for elsewhere: a metric named
after its expected sign cannot report the other one without sounding like a mistake.

### 12.15 Cost per page, and the run list that would have halved it

2026-09-20. Section 10 asks for cost per page and names the source: the gateway ledger.
`sever cost` reads it, and `sever report` splices the line into the README from
`results/cost.json`, which is committed for the same reason the answer cache is: the ledger
is in project 04's working copy and nobody cloning this repository has one, so the number is
recorded, dated and attributed rather than left unreproducible.

**US$0.00456 per page**, CA$0.00615 at the portfolio's planning rate. US$0.9571 across 871
paid calls over 210 pages. Against a CA$55 budget, a full run of the corpus costs under a
cent a page and the whole project has spent CA$1.53.

The first implementation totalled one run id and was wrong in the flattering direction.
`sever-full-210` paid for 466 calls, but it answered the corpus partly out of answers that
`sever-full-001`, `sever-sweep-210` and `sever-retype-210` had already paid for. Reported
alone it gives US$0.00243 per page, which is half the truth, and nothing in the output would
have said so.

What makes it checkable is an identity that happens to hold: the committed answer cache has
one line per distinct answer, the ledger has one row per paid call, every cached answer was
paid for exactly once, and so the two counts must be equal. They are, at 871. `from_ledger`
refuses to write a figure when they are not, in either direction, and `tests/test_cost.py`
holds both directions with the real shape of the failure in the first case. Adding a paid
run against this corpus and forgetting to list it now breaks the command rather than
quietly discounting the price.

**Two numbers, because one of them does not transfer.** The deduplicated figure is a
property of a template-generated corpus: 67 percent of the requests in a run are
byte-identical to one already made, because the personas are substituted into a small set of
templates. Real records do not repeat like that. So the line also prints what the same pages
would cost with no deduplication, about US$0.0136 each, and says that is the figure to read
if your documents are not generated from templates. It is the less flattering number and it
is the one a public body would actually budget against.

### 12.16 The reviewer application, and the rule it turned out nobody was keeping

2026-09-20. `sever review` exists. One page at a time, the record rendered as the characters
the redaction is computed from, every proposal with its category, its provision and its
reason, and an action required on every span before the page can be completed.

**The rule the build found broken.** CLAUDE.md says no code path produces a released
document without a reviewer action on every page. That was true only because nothing
released anything, and it stopped being true the moment it was examined: `sever export` had
been writing files named `{doc_id}-released.pdf` since the export module landed, from
proposals no person had seen. The redactions in them were real and the leak test passed on
them, which is exactly why the name mattered. It now writes `-proposed.pdf` unless
`--audit` points at a log in which a person completed every page of that document, and the
gate that decides is `Session.release_gate`, which raises rather than returning a boolean:
a caller who forgets to check a boolean releases the document.

**The control arm is a design decision, not a flag.** Section 10 wants reviewer minutes per
page with and without proposals, so `sever review --mode unaided` serves the same records
with the proposals dropped *before the session is constructed*. Hiding them in the template
would have been one edit away from not being a control, and an arm that highlighted the
spans while hiding only the suggested category would have measured how long it takes to
agree with a highlight. Finding the span is most of the work.

**The clock is not the audit log.** The log has timestamps, but the first action on a page
is not the moment the page appeared, and a page that took four minutes of reading and one
click would be recorded as instantaneous. The session stamps a page when it is served and
measures to the completion action, into `review/timings.jsonl`, separately: the audit log is
evidence of decisions and is not the place for interface telemetry. A page completed after a
restart has no stamp and is recorded as untimed rather than estimated, and
`sever eval-reviewer --audit` prints how many completed pages the study could not see,
because a study that cannot say how much it missed is not reporting, it is selecting.

**A deviation from section 7.** The plan said htmx over Jinja. There is no htmx and no
script from anywhere: server-rendered HTML, form posts, and about thirty lines in
`base.html` doing the swap htmx would have done. The reason is the subject matter. A tool
for reading access-to-information records asks a public body to trust a third party it did
not choose every time a page loads a script from a CDN, and the answer to "can we run this
with the network cable out" should be yes. The cost is thirty lines that will never be
anyone's favourite code. The benefit is a dependency list with nothing in it that phones
anywhere.

**What is still missing, and it is a person.** The application records the study; nobody has
run it. `results/reviewer.md` says so in those words rather than reporting an empty table,
and `sever eval-reviewer` refuses to print a ratio until both arms have reached three
documents, because two sessions on one record produce a computable number that means
nothing and would be read as measured.

### 12.17 Reading the statutes, and three mappings that were wrong

2026-09-20. All 36 provisions are verified: quote, date checked, URL checked against.
Federal current to 2026-07-21, ATIPPA to the Assembly's consolidation at 2026 c16 s2. The
count was 18 of 33 and the rest were carrying a written reason for not having been checked,
which is the honest state but not the finished one.

Reading them was not clerical. Three of the NL mappings were wrong, and none of the three
was wrong in the direction the open questions had guessed.

**K2 is (f), (g) and (h).** This was the item flagged as largest, correctly: K2 carries
2,345 of the corpus's 5,355 spans. The letters were right to refuse to guess, and they are
now confirmed. What the confirmation added is a limit nobody had written down: paragraph (h)
releases an opinion given in the course of performing services "except where they are given
in respect of another individual". An official's assessment of a member of the public is
therefore R1 and not K2. The tool cannot see that distinction and the schedule would have
argued the wrong way about it.

**K4 is a weighing with no period in it.** The federal Act excludes a person dead more than
twenty years from the definition of personal information outright. ATIPPA 40(5)(j) makes the
time since death a circumstance the head of a public body weighs, and states no period at
all. So a K4 that releases after a fixed number of years is wrong twice under this
jurisdiction: it performs a weighing the Act reserves to a person, and it weighs against a
threshold this project invented. K4 escalates under the NL configuration. This was on the
open list and is now decided.

**K3 is far narrower than assumed, and this one was not on the list.** There is no general
publicly-available exception in ATIPPA in the terms of the federal 19(2)(b). Paragraph
40(2)(m) releases two enumerated things, attendance at a public event and receipt of an
honour, and only where the disclosure is not contrary to the public interest. A name that
is already public for any other reason is not released by it. Under the NL configuration
anything K3 reaches through general "already public" reasoning escalates.

**What this does to the numbers, and the answer is nothing yet.** Every published figure in
this repository comes from the federal configuration. The NL configuration has never been
scored, so three codes moving toward escalation change no table here. What it does do is
make the NL configuration a different tool from the federal one in a way the taxonomy now
records, and scoring it would be a statement about two statutes rather than about this
software. Not measured, not claimed, and worth doing.

**The one place a verbatim quote and this repository's punctuation rule collide.** The
marginal note of ATIA section 23 is printed with an em dash. The quote here uses a hyphen
and `federal.yaml` says so beside it, because silently normalising a quotation is the kind
of small dishonesty this whole file format exists to prevent.

### 12.18 A documented difference the software did not implement

2026-09-20, immediately after 12.17. Writing up what the statutes said produced two
sentences in `docs/escalation.md` of the form "under the NL configuration K4 escalates",
and they were false. `decision` lived only in `categories.yaml`, which has no jurisdiction
in it, so `taxonomy.decision("K4")` returned `keep` whatever statute was configured. The
taxonomy could record the difference in a note and the pipeline would carry on releasing.

That is worse than not having noticed. An undocumented difference is a gap; a documented
one is a description of behaviour, and a reader has no reason to check it against the code.
The note would have been read as a statement about what the tool does.

**What changed.** A jurisdiction's mapping for a code may now carry `decision` and
`decision_reason`, and the loader refuses the first without the second: the override
changes what is released, and the reason is what a reviewer or an auditor reads.
`Taxonomy.decision(code, jurisdiction)` honours it, `DecisionEngine` passes the
jurisdiction it was configured with, and `docs/taxonomy.md` grows a table of every code a
jurisdiction decides differently, with the reason, because a difference between two
configurations of the same tool should not have to be found by diffing YAML.

`score()` takes a jurisdiction too, and that is the subtle half. A label's code is ground
truth about a question; what that code *does* is a fact about a statute. Scoring an NL run
against federal ground truth would count a correctly escalated span as an error, silently,
in whichever direction happened to match.

**The guard.** Federal overrides nothing, every published figure in this repository is
federal, and `tests/test_jurisdiction_decisions.py` asserts both: that the federal
configuration's override set is empty and that every code decides federally exactly as
`categories.yaml` says. Re-running `sever report` after the change produced a byte-identical
results file, which is the evidence rather than the intention.

**The expected frequency of this field is close to zero, and that is deliberate.** A code
whose decision changes between jurisdictions is usually two codes wearing one name. Two
statutes genuinely disagreeing about the same question is the case it is for, and both
instances here came from reading the Act rather than from designing the taxonomy.

### 12.19 Scoring the other statute, and a whole class of failure nothing could see

2026-09-20. `sever report --jurisdiction nl` exists, and running it answered the question
12.17 left open, then asked a much worse one.

**The overrides are inert on this corpus, and that is the small finding.** The rules never
propose K3 or K4 at all: `deceased_over_twenty_years` needs a date of death in the record
and `already_published` needs a public-register match, and on 210 documents neither fires.
So the NL configuration scores 31.2 percent over-redaction against the federal 30.3, and
the difference is not behaviour, it is the denominator: 350 spans leave the must-keep pool
because their true decision is now escalate. Escalation, leak rate and recall are identical
to the decimal.

**The large finding is what happened to those 350 spans.** `must_redact` is REDACT and
`must_keep` is KEEP. Federally no code's true decision is escalate, so the third case was
empty, and every published rate covered every span by accident rather than by design.
Override two codes to escalate and 350 spans fall into a state that the leak rate skips and
the over-redaction rate skips.

They are not being escalated. They are being **released**, under some other keeping code,
because the rules never proposed K3 or K4 in the first place and something else reached them
first.

| System | Spans ATIPPA reserves for a person | Released anyway |
|---|---:|---|
| sever, rules only | 350 | **78.9%** (74.4 to 83.1) |
| sentence-only, no document context | 350 | 40.6% (36.3 to 44.6) |
| blunt redact-all-PII | 350 | 0.0% (0.0 to 0.0) |

Nearly four in five. Under the NL statute this tool settles, silently and by machine, a
question the Act assigns to the head of a public body, and not one published number moved
when it started doing so.

**So there is a new rate.** `unweighed_release_rate`: of the spans the configured statute
reserves for a person, how many the machine released. It is deliberately not folded into the
leak rate, because it is a different failure. A leak is the wrong answer. This is an answer
where the Act asked for a judgement, and the information might well have been releasable:
nobody looked. For a tool whose first claim is "the tool proposes; a person decides", that
distinction is the whole product.

Where the statute reserves nothing the cell is n/a rather than 0.0 percent, and the table
does not render at all. A column of zeroes reads as a perfect score; there is no question
being scored.

**The pattern, for the fourth time in this build.** Every metric here had a denominator that
happened to cover everything, until a change made it not. Recall could not see a wrong label
until a name was typed as a place. The two-bucket decomposition blamed the rules until the
third bucket existed. Now the leak and over-redaction rates turn out to have been a
partition only because one configuration had no escalating ground truth. The lesson is not
"add a bucket". It is that a rate whose denominator is "everything, as it happens" is one
configuration change away from being a rate about a subset, silently.

**What this does not claim.** Every headline figure in the README is still the federal
configuration and none of them moved. The NL run is in `results/nl/` and is labelled with
its jurisdiction in its own first line. Nothing here says the tool is worse than it was; it
says there was a question nobody was asking.

### 12.20 04's email leak was here too, and the corpus could not have found it

2026-09-20. Project 04's redaction harness found a leak on its first run:
`therese.gagne@example.gov.nl.ca`, spelled with its accents, matched neither their
recogniser nor their second pass, because an address carrying no digit is not
identifier-shaped and a lowercase word is not name-shaped. It went out in clear.

The same hole was here, and worse, because it did not need the accents.
`scrub_unrecognised` passed **any** email address through untouched, plain ASCII included,
and a Canadian postal code with it: `A1B 2C3` is all caps so it is not name-shaped, and it
starts with a letter so the digit run does not reach it.

Every test passed. The EMAIL recogniser finds these, so the corpus-wide leak test never put
the question to the second pass, and the second pass was never asked whether it could hold
alone. That is precisely the arrangement `docs/rejected.md` entry 2 calls not a boundary: a
backstop that holds only while the thing it is backing works is not a backstop. And it has
already failed once here for real. Entry 2 records Presidio missing
`aaronpenashue@gov.nl.ca.example` outright; on that occasion nothing whatsoever would have
caught it.

Fixed in `scrub_unrecognised`: address-shaped and postcode-shaped text is masked whether or
not any recogniser claimed it, in any script. `tests/test_scrub_shapes.py` holds both
against the function directly, with no detector in the picture, which is the only way to
test a backstop.

**The corpus cannot find this class of defect and the generator says so now.** `_slug`
transliterates, deliberately and for good reasons that are written down, so every address
this corpus produces is ASCII. Its docstring used to say an accented address "is not a
thing this tool will meet". It is now qualified, because 04 has evidence to the contrary,
and it names the test that stands in for the corpus. A shape the generator cannot emit has
no coverage unless a fixture gives it some.

This is the fourth defect in this project found by an outside report rather than by a test,
and all four arrived the same way: someone else measured something, published what it found,
and the shape of their finding turned out to name a hole here. It is a better yield than any
tool in this repository has managed.

### 12.21 Precision, and a number that was misnamed rather than missing

Same day, same exchange. 04 published detector precision and called it "the number this
repository has never had". It is not one this project can honestly publish in the same form,
and the reason is a difference in how the two corpora are built.

04's corpus plants values in prose written to contain none, so a span outside a label is a
false positive by construction. This corpus is not built that way. Its templates carry real
dates, real department names and real job titles, all genuine entities and none of them
persona values. Of 229 detections outside the labelled set in twenty documents, the
breakdown is 107 dates, 77 organisations, 36 job titles and 9 places, and almost all of them
are the detector correctly finding something that is correctly not personal information.

So `false_positive_spans` was a misleading name for a number that mostly counted correct
behaviour, and it has been publishing since the first results table. It is now
`unlabelled_detections`, with `unlabelled_detections_withheld` beside it, which is the part
that means something: a detection outside the labelled set only costs the requester if the
decision layer went on to put a box over it.

**That number is 16 of 229, and every single one is a bare job title.** "Minister",
"Deputy Minister", "Manager", "officer": the detector claims the title, no person is
attached to it, the rules cannot place it, so it escalates, and escalation withholds. The
tool puts a box over the word "Minister" about once per document, and a reviewer has to
clear each one. That is a small version of exactly what this project criticises the blunt
baseline for.

Recorded here rather than fixed in the same commit, deliberately. The fix is a rules change
that moves published numbers, and it should be measured against a run that is not also
changing for other reasons.

### 12.22 The scanned track, and OCR costs the column nobody expected

2026-09-20. Tesseract is installed, the scan track is built and measured, and section 10's
"native and scanned tracks" line has a table under it. 50 documents, four degradation
profiles, `results/scanned.md`.

| Input | Character error rate | Labels that survived | Detector recall | Leak rate | Over-redaction |
|---|---:|---:|---|---|---|
| native (no OCR) | 0.0% | 100.0% | 98.0% | 3.0% | **28.7%** |
| clean | 0.7% | 100.0% | 97.3% | 3.0% | **48.3%** |
| scanner | 0.6% | 100.0% | 97.6% | 3.6% | **48.9%** |
| photocopy | 0.9% | 99.9% | 96.8% | 3.9% | **48.1%** |
| fax | 65.1% | 45.2% | 52.9% | 69.2% | 36.7% |

**The column that moves is not the one anyone worries about.** The fear about OCR is that a
misread name gets released. On these numbers that barely happens until the page falls apart
entirely. What happens first is that the requester gets a blacker page: a near-perfect scan
costs about a fifth of a point of recall and **twenty points of over-redaction**.

The mechanism is structural rather than textual, and it is the reason a character error
rate alone would have missed it. The characters are almost all there. The *layout* is not.
`paragraph_blocks` recovers where the paragraphs are and nothing more, so every block is
BODY, nothing is `is_role_bearing`, and the rules lose the signature block and the
letterhead. Those are the evidence they lean on hardest to tell an official acting in an
official capacity from a third party: a name in a signature block is a signer, the same
name in body text is just a name. Unable to place the person, the rules escalate, and
escalation withholds.

This is the sentence-only ablation arriving by a different road. That ablation blanks the
document context on purpose and reports 58 percent over-redaction; a scan blanks a
particular slice of it by accident and reports 48. The two agree about what the context is
worth, which is the closest thing to a corroborated result this project has.

**The three profiles that work all work about equally.** Between 0.6 and 0.9 percent
character error, nothing moves outside the intervals. That is worth knowing because it says
the scan quality knob is not where the effort belongs: improving a 0.9 percent error rate
to 0.6 buys nothing, and recovering block structure from the word geometry Tesseract already
returns would buy twenty points. The scan track's finding is a layout-analysis todo, not an
OCR one.

**The fax row is where it falls out**, and it falls out completely rather than gradually:
65 percent character error, 45 percent of labelled values gone from the page entirely, and
a leak rate over the ones still there of 69 percent. 100 dpi is below what 9.5 point text
survives. It is kept in the table because knowing where the floor is beats four rows that
all work, and its denominators are smaller than the rows above precisely because half the
values are no longer on the page to leak.

**What the track is not.** These are renders of synthetic records put through a simulated
scanner, not photographs of paper. Real scans bring skew that varies down the page, staples,
punch holes, marginalia and records that were already photocopies when they were filed. And
the corpus renders in Courier, monospaced and high contrast, which is close to the easiest
thing an OCR engine can be handed: the `clean` row is a floor, not a typical case, and it is
not zero even so.

**A side effect worth naming.** The PDF leak test has had an OCR channel since it was
written and has never run it, because Tesseract was not installed. It runs now, and the
published leak test is no longer "text layer only": it renders every applied box and reads
the pixels. The claim was always that the text under the box is gone; now both channels have
been asked.

### 12.23 The model-only baseline, and what the rules are actually worth

2026-09-20. The last missing baseline. Same model, same context record, same confidence
threshold, `rules=()` so every span is sent rather than only the residual the rules could
not settle. The difference between it and the row above is the deterministic layer and
nothing else.

| System | Leak rate | Over-redaction | Escalation |
|---|---|---|---|
| sever, rules then the model on the residual | 5.3% (4.1 to 6.5) | **23.3%** (21.9 to 24.6) | 27.7% |
| model-only, no rules | 4.8% (3.8 to 5.8) | **41.9%** (39.4 to 44.4) | 42.3% |
| sever, rules only | 2.8% (1.8 to 4.0) | 30.3% (29.1 to 31.4) | 46.5% |
| blunt redact-all-PII | 1.1% (0.6 to 1.7) | 98.5% (97.9 to 99.0) | 0.0% |
| sentence-only, no document context | 2.8% (1.8 to 4.0) | 58.0% (56.0 to 59.9) | 66.9% |

**The rules are worth eighteen points of over-redaction and nothing at all on leaks.** The
leak columns are 5.3 and 4.8 with overlapping intervals, so on this corpus the rules do not
make the tool safer. What they do is make its output usable: without them the model withholds
nearly twice as much of what must be released, and escalates half again as often.

That is the opposite of how a rules-plus-model architecture is usually justified. The pitch
is that deterministic rules are the safety net under a probabilistic model. Here the model is
about as safe on its own, and the rules earn their place by being **decisive**: they settle
the cases that have a settled answer, so the model is only asked the genuinely ambiguous
ones, and a model asked only hard questions escalates less than a model asked everything.

**Read it against the sentence-only row and the picture completes.** Sentence-only is the
same rules with the document context blanked: 58 percent over-redaction. Model-only is the
same context with the rules removed: 41.9. Neither component is carrying the tool. The
configuration that works is the one with both, at 23.3, and each ablation costs roughly
what the other does.

**What it cost, and why that number is kept separate.** 1,357 new paid calls, US$1.46, on
top of the US$0.96 the pipeline's own rows cost. The baseline asks about every span rather
than the residual, so it is the most expensive row in the table by a factor of three, and
its spend is a cost of *measuring* the tool rather than of running it. `sever cost` reports
the two separately for that reason: folding them together would have published a cost per
page more than double the tool's, for a configuration nobody would deploy. Total project
spend is now US$2.60, about CA$3.51, against a CA$55 budget.

The answers are in the committed cache like every other row, so the model-only baseline
replays for nothing from a clone with no key.

### 12.24 Measuring the backstop by taking the detector away

2026-09-20, from project 04 and the best idea either project has had this week. Their
masking column read 100 percent everywhere with every recogniser present, and they noticed
what that meant: "a masking column where a recogniser is doing the work says nothing about
the layer that exists for when a recogniser is wrong." So they run every case twice, once
as normal and once with every recogniser removed, and print both. It found two holes on the
first run.

The same test now exists here: every persona value on every page of the corpus, with the
detector taken away entirely, nothing substituted, and only `scrub_unrecognised` standing
between the value and the request.

**It holds all of them.** And there is a second piece of evidence for that which is better
than the assertion, because it was not arranged: after changing the second pass three times
today, the committed answer cache still replays with no misses. A cache key is a hash of
the outbound message, so an unchanged key means an unchanged message, which means **the
second pass was not altering a single request in the corpus.** It was inert, exactly as 04
predicted, and the only way to find that out was to remove the layer above it.

**Their bracketed phone number was here too.** `(709) 555-0199` came out as
`(709) [NUMBER?]`: the bracket ended the digit run, the rest was masked on its own, and the
area code went out in clear beside its own placeholder, which is worse than leaving the
whole thing alone because it advertises the shape of what was removed. Their rule is now
this project's rule: a bracket may join a run but may not widen what gets masked, so a run
containing a bracket needs seven digits before it is masked at all. `section 40(2)(f)`,
`page 12 of 40` and `see s. 19(1)(a)` stay readable, with a test on each, and a released
record that could not cite the provision it severs under would be its own kind of failure.

**Their date limit is this project's limit and is now written down.** `14 March 1978` has no
backstop and will not get one. Masking every date written in words would black out the dates
a decision turns on: whether someone died more than twenty years ago is the whole of K4 and
the year is what answers it. The recogniser handles the shape by requiring a label word in
front of it, which is the same judgement made where there is enough context to make it. 04
reached the identical conclusion on the identical shape the same day and left theirs at 66.7
percent rather than masking it. A test now pins the limit, so changing that judgement means
changing a test rather than discovering the gap in a release.

**And the new 100 percent gets the warning it deserves.** It reads 100 because every secret
this corpus puts on a page is name-shaped, digit-shaped, address-shaped or postcode-shaped,
and those are the four shapes the second pass knows. The shape known to defeat it is one
this corpus never generates, because persona dates of birth are ISO. It is a measurement
against the shapes somebody thought to generate, like every recall figure here, and it is
labelled as one in the test that produces it.

**On precision, 04 agreed the number should not be manufactured** and added the part worth
keeping: their corpus labels departments as ORGANISATION and towns as LOCATION, marked
impersonal, so a detector that finds them is not punished for being right while the leak
rate stays a count of personal values. Job titles are the case they have not covered and,
on this project's evidence, the ones that cost. That is a corpus design idea worth taking if
this corpus ever grows a precision column.

**The tally, since both projects are keeping one.** Eleven defects on their side this week,
two from reports here and the rest from probing or from their harness. Four on this side
from their reports. Neither project's test suite found any of them.

### 12.25 Two footguns in this project's own tooling, both found by using it

2026-09-20. Neither of these is a redaction defect. Both are ways the machinery that
publishes the numbers can quietly publish the wrong ones, which for a project whose entire
claim is "every number here is generated, none is typed" is the same category of failure.

**A partial run overwrote a complete one, and said "updated".**
`sever report --readme README.md --no-pdf-leak` deleted the PDF leak table from the README.
The flag did exactly what it says. The run succeeded, the command printed
`README.md: updated`, and a published result was gone. The generated block is the one part
of the README that changes without a person reading the diff, which is the whole point of
it and also the reason it needs a check a person would otherwise have to remember.

`splice_into_readme` now refuses a block that would remove a section the README already
publishes, and `tests/test_readme_splice.py` holds the case. The guard is about losing
something rather than about being complete: a README that has never published the leak table
is not made worse by a run without it.

**`sever cost` and `sever report` are a cycle, and the order matters.** Cost reads
`model_asks` out of `results.json`; report reads `cost.json` to splice its line. Running
report and then cost in one chain spliced the *previous* cost figure into the README and
only then recomputed it, which is how a line reading "the pipeline asked 10,251 times"
reached a published table for a pipeline that asked 2,606. Documented at the top of
`sever/eval/cost.py`, with a test that the note and the default path still agree. Cost
first, then report; both are free.

The second one is worth a sentence beyond the fix. The wrong number was not wrong by a
little. It was the model-only baseline's ask count standing in for the tool's, which would
have published the tool as four times more cacheable than it is, in the one table that is
supposed to need no trust. It was caught by reading the output, which is the same way most
of the defects this week were caught, and not by anything in the suite.

### 12.26 The box over the word "Minister", and two modules that disagreed

2026-09-21. Deferred from 12.21 so it could be measured against a run that was not changing
for other reasons. That run exists now, so here is the change.

A job title with any other person mentioned in the same sentence used to yield from
`not_personal_information`, on the reasoning that "a title beside a name may be identifying
in a small unit". Written on the first build day. No test ever covered it. Renaming
`false_positive_spans` found what it actually did: **every span this tool withheld that no
persona owned was a bare job title escalated by this guard.** Sixteen in twenty documents,
"Minister", "Deputy Minister", "Manager", "officer", about one box over the word "Minister"
per page, each one a decision a reviewer has to make and clear.

**The argument that settled it was not the count.** It was that the guard put two modules
of this project in flat contradiction. `placeholders.NOT_SUBSTITUTED` holds JOB_TITLE and
explains why in as many words: "Regional Director is a position, not a person", and
substituting it would delete the evidence the K2 decision rests on. So the tool was sending
a title to a vendor on the grounds that it is not personal information, and then putting a
box over the same title on the grounds that it might be. Both cannot be right, and the
taxonomy agrees with the boundary: K6 is "not information about an identifiable individual",
and a public office is exactly that.

**What was real in the concern is narrower than the guard.** An office held by one person in
a small unit can name them as surely as their name would. That is not a property of the word
"Minister", it is not detectable from a co-mention count, and it needs someone who knows the
organisation. It is in `docs/escalation.md` as a thing this tool does not decide, which is
where it should have been from the start.

**The change came with its own guard, in the same commit and deliberately.** JOB_TITLE
joined `sweep._RELEASING_TYPES`, so a person's name wrongly typed as a job title is re-typed
to PERSON before the rule can release it. That is the "Tuglavina typed as a LOCATION" defect
of 12.13 waiting one entity type over, and a releasing type needs that protection the moment
it starts releasing. Shipping the two in separate commits is how a leak class gets introduced
by a change that reads as a simplification.

**Measured on twenty documents before the full run:** spurious withholding 16 to 0, and it
moved the headline columns the right way as a side effect rather than as the point.

The pattern this project keeps meeting, now from a fifth direction: the defect was not in a
component, it was in two components that were each defensible alone and disagreed with each
other. Nothing that tests a module in isolation can see that, and the thing that found it was
a metric renamed because its name was wrong.

### 12.27 Fixing the rules halved the case for the model layer

2026-09-21, an hour after 12.26 and the most consequential thing in this file.

The job-title change was measured on twenty documents as a fix for spurious withholding. On
the full corpus it moved the headline table:

| System | Leak rate | Over-redaction | Escalation |
|---|---|---|---|
| sever, rules then the model | 5.3% (unchanged) | **23.3 to 20.5** | 27.7 to 25.7 |
| sever, rules only | 2.8% (unchanged) | **30.3 to 23.2** | 46.5 to 41.2 |
| model-only, no rules | 4.8% (unchanged) | 41.9 (unchanged) | 42.3 (unchanged) |
| sentence-only | 2.8% (unchanged) | 58.0 to 48.9 | 66.9 to 60.2 |

Seven points off the rules-only row and not one leak rate moved. The model-only row is
unchanged to the decimal, which is the sanity check: it has no rules, so the guard never
applied to it.

**And that is what makes the model layer's case collapse.** The exchange rate the README has
been publishing was: turn the model on and it correctly releases 277 spans the rules
withheld while wrongly releasing 35 that had to go. Eight to one. It is now **107 against
35. Three to one.**

Nothing about the model changed. A good part of what it had been earning its keep on was
cleaning up after a deterministic bug, and the moment the bug went, so did most of its
value. Three to one for 2.7 points of over-redaction against 2.5 points of leak is thin
enough that the rules-only configuration is now the defensible default, which is fortunately
what the tool already does with no flags.

**The general warning is worth more than this project's number.** A model layer measured on
top of an imperfect deterministic layer is partly being paid to fix it, and that payment is
invisible until the deterministic layer improves. Anyone comparing "rules" against "rules
plus a model" is measuring the rules they happen to have, not the architecture. This project
published an eight-to-one figure in good faith for a week, and the measurement that
overturned it was not aimed at the model at all: it was a metric renamed because its name
was wrong.

**One consequence went the other way, and it is recorded rather than buried.** Under ATIPPA
the same change made things worse: unweighed releases went from 78.9 percent to 89.7. A
public figure's title used to be escalated by the guard and is now released as "not
information about an identifiable individual", which is right federally, where K3 releases
anyway, and wrong under a statute with no general publicly-available exception. The
jurisdiction override cannot reach it, because that machinery changes what a code decides
and the tool is not proposing K3 here; it is proposing K6 about a span the ground truth says
is a person's public information. A labelling problem wearing a decision problem's clothes,
for the third time. `docs/escalation.md` carries the breakdown.

So the change is an improvement federally, a regression provincially, and the honest
statement is both.

### 12.28 The real-record track, built without a fetcher on purpose

2026-09-21. Section 10's last measurement that is not waiting on a person: over-redaction on
records a public body actually released. Loader, guard, measurement and `sever eval-releases`
are built and tested. No package has been downloaded, and `results/releases.md` says so
rather than reporting a rate.

**Why there is no fetcher, which is the decision worth recording.** Library and Archives
Canada serves completed release packages free of charge, behind a JavaScript front end whose
search runs on an undocumented POST endpoint. I found the endpoint, worked out the payload
shape from the site's own `DataService.js`, and then stopped. Three reasons, in order of
weight: a published number that depends on an undocumented endpoint staying stable is not
reproducible in the way everything else here is; automated access is not a use the site
documents, and the terms I could find cover reproduction rather than scraping; and the
records are archival, which is a weaker match for a tool aimed at modern records about
living people than the effort implied.

So the track is manifest-driven. A person downloads packages, `sever releases add` records
each with its sha256, source URL and retrieval date, and **the manifest is committed while
the PDFs are not**. Anyone can obtain the same bytes from the same URLs and reproduce the
number, or get a checksum failure naming the file that differs. That is slower than a
fetcher and more honest than one, and it is what section 3's data rules already asked for:
"Loaders fetch and verify checksums; the manifest is committed."

**The guard is the part of this I would keep if I had to throw the rest away.** A released
PDF is supposed to have had the text under its boxes removed. Not all of them do. A package
that merely draws rectangles over live text still carries the withheld names in its text
layer, and this loader would read those as visible and count every one as a must-keep label,
marking this tool down for proposing to redact exactly what the reviewer redacted. A
measurement that punishes agreement is worse than no measurement. `inspect_redaction` reads
the text inside every filled rectangle and excludes the package with a reason, which is the
question `sever/eval/pdf_leak.py` asks of this project's own exports, turned around and asked
of somebody else's. A package with no rectangles at all is reported as *unchecked* rather
than sound, because claiming a check that did not happen is the same error one level down.

**Two handicaps this track carries, both stated in its own output.** A released PDF is a
flat text layer, so nothing says which paragraph was a signature block and every block is
body text; `results/scanned.md` measures what that costs where the truth is known, and it is
about twenty points of over-redaction. And there is no configured requester on a downloaded
package, so every span that would have been K1 is something else here. Both push the same
way, so the figure is a floor.

**And the denominator is a choice, so both are printed.** The headline counts spans that
could be personal information; the second row counts every detected span including the
organisations, places, job titles and dates the tool releases by design. A package full of
department names would move a blended rate without saying anything about a decision anybody
would argue with, and a reader should be able to see the effect of that choice rather than
trust it.

What is left for this track is not code. It is somebody downloading sixty to a hundred pages.

### 12.29 The study is one command, and the export was not reading the reviewer

2026-10-01. Section 5 had four reviewers doing twenty pages each "with and without
proposals", and `sever review --mode` timed one arm at a time. Read literally that is the
same twenty pages twice per person, which measures memory: the second pass is fast because
the reviewer has read the letter. `sever study` replaces it with a crossover. Twenty test
split records are dealt into two halves balanced by document type; each reviewer does one
half with proposals and the other unaided and never sees a record twice; the halves swap
between reviewers 1 and 2 and the order swaps between 1-2 and 3-4. Each arm opens with a
practice page that is timed, recorded and left out. The record-by-record ratio over records
reviewed in both arms is the figure to quote, because it holds the documents fixed.

Two things were added because the study would have been unfair without them. Every page
now names the requester and offers the release rules and the public register, since the
tool is configured with those facts and an unaided reviewer was not. And a reviewer's own
severances are now drawn on the page with an Undo, because in the unaided arm those are
all of them and they had been invisible once made. The highlighted button on each proposal
is now the one the tool proposes; it had been Withhold on every span, which nudged a
reviewer towards withholding the officials the tool proposed to release.

Accuracy is scored beside speed, per arm, against the labels, with the tool's unreviewed
proposals on the same records as the reference row. An arm that is fast because the
reviewer accepted everything unread is measuring trust, not help.

**Building it found a leak in the export.** `sever export --audit` checked that every page
had a completion row and then applied the tool's *proposals*. A rejected proposal was
still severed, and a name a reviewer selected and severed because the detector had missed
it was released in clear. `sever.review.decisions.final_spans` now reads the log and the
proposals together, the export and the schedule apply its answer, and
`tests/test_export_reads_decisions.py` checks the PDF. The released-record screen had the
related fault that a span moved from R1 to R2 dropped out of its schedule, because
`CHANGE_CATEGORY` withholds or releases depending on the code, which only the taxonomy
knows.

### 12.30 Through the gate at last, and it blocks the model layer

2026-10-01. Section 4 promised `eval/gate/` and the README said "measured with the AI
Release Gate"; until today only the estimator was shared. 03 built its adapter for
downstream projects on 2026-09-30 and `sever gate-export` now writes a spec and one side
file per configuration. The comparison is rules only against rules then the model,
replayed from the committed answers.

The item is the document. The gate has no cluster awareness and treats every item as
independent, so span ids would hand it 5,355 items that are really 210. One suite per
question: no leak in the document, none of the requester's information withheld, nothing
public withheld, nothing impersonal withheld. K2 and K4 were suites in the first export
and were dropped on evidence: one document in 210, and one in 35, had every such span
right under either configuration, so a document verdict could not separate them. Their
span-level rates stay the measurement for those two.

The gate blocks, on `no_leak`: 35 documents worse with the model and none better. That is
the README's "35 wrongly released" seen through a different test, and it moves the
recommendation from "rules only is defensible" to "rules only is what the release gate
allows".

### 12.31 A staff directory, and why it matches on the email address only

2026-10-01. Over-redaction of officials is the weakest published number, and most of it is
escalation of names and work contacts the record never pairs with a title. Peter asked for
a public list of officials modelled on 04's allow list. `sever.context.directory` is that
list and `staff_directory` the rule that reads it, late in the order and off unless a
directory is configured. `sever eval-directory` builds a synthetic directory from the
corpus's officials at 50, 80 and 100 percent coverage.

Matched on names and work contacts it multiplied the leak rate by twelve (2.8 to 32.9
percent at full coverage). Part of that is the corpus's small name pool and thousand-number
telephone block, which a real province does not have; but 129 of the 422 leaks were the
listed employee themselves, a grievant in their own complaint, which no larger pool fixes.
Matched on the work email alone it took officials' over-redaction from 30.7 to 20.3
percent and leaked nothing. That is the default for a configured directory now, and
`docs/rejected.md` entry 6 records the name match as the rejected approach. The headline
stays directory-free.

