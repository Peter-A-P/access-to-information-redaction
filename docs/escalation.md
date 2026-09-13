# Where this tool declines to decide

A redaction tool that answers every question is either very good or lying. This one
declines, on purpose, in the cases below. An escalated span is **withheld** in the
proposal and flagged with the question the tool could not answer, so the failure mode of
declining is a reviewer's time, not a person's privacy.

This page is part of the deliverable. If you are evaluating the tool, read it before the
results table: the escalation rate is the price of the leak rate, and you cannot judge one
without the other.

## The rule behind all of it

> An undecided span is proposed for redaction and flagged. There is no path through the
> decision layer that releases a span because nothing matched.

Enforced in `sever/decide/pipeline.py`, where the fallthrough is `E1`, and `E1` carries the
escalate decision, and escalate withholds. `tests/test_rules.py::
test_no_rule_path_releases_an_undecided_span` walks every entity type through the rules and
asserts it.

## The cases

### 1. The role is not in the record (`E1`)

A name with no title anywhere in the document, no signature-block or letterhead mention,
no public-register entry and no match to the configured requester. The record does not say
whether this is an official or a member of the public, and the difference decides the
category completely.

This is the largest single source of escalation and it is the honest answer. A surname in
a distribution list genuinely does not carry its own capacity.

### 2. A partial name that could be the requester or could be someone else (`E1`)

"Byrne" where the requester is Aaron Byrne and a Siobhan Byrne also appears in the record.
This is the one case that never reaches the model, because both errors are unacceptable:
call it the requester and a third party's information is released to a stranger; call it
the third party and a person's own file comes back to them with their name blacked out.

### 3. A mixed span (`E2`)

The requester and another named individual in one sentence, entangled so that severing
cleanly is a judgement. Severance is mandatory (federally, Access to Information Act
s. 25; in Newfoundland and Labrador, ATIPPA s. 8(2)), but the statute makes it mandatory
*where it is reasonable*, and "reasonable" is the reviewer's word.

### 4. A death inside twenty years (`E1`)

The twenty-year rule is a hard exclusion federally and the tool applies it only when the
record itself states a date. A death recorded within twenty years does **not** qualify, and
the tool escalates rather than falling back on a guess about whether the person is alive.
Absent any date, the span falls through to case 1.

### 5. The model was not confident enough

Below the configured confidence threshold, a model answer is discarded and the span is
escalated with the model's reasoning attached, so the reviewer sees what it thought and
why it was not trusted.

### 6. The rules and the model disagreed

Not resolved silently in either direction. The proposal is the withholding one and the
reviewer is shown both answers, because a disagreement between a deterministic rule and a
model is information about the document, not noise to be averaged away.

## What is out of scope rather than escalated

These are not escalations. The tool does not attempt them at all, and says so.

- **Non-personal exemptions.** Advice and recommendations, solicitor-client privilege, law
  enforcement, a third party's business interests. Surfaced as `E3` flags with the
  provision and **no proposal**. This tool decides personal-information questions.
- **The Newfoundland and Labrador public-interest override** (ATIPPA s. 9). Not applied and
  not flagged.
- **The section 40(5) balancing test** under ATIPPA. The NL configuration's `R1` means
  "presumptively an unreasonable invasion, for the reviewer to weigh", not "the balance has
  been struck". This is a real difference from the federal position and it is recorded in
  `sever/taxonomy/nl.yaml` as well as here.
- **Handwriting.** Scanned typed documents only.
- **Release.** There is no code path from a proposal to a released document without a
  reviewer action on every page.

## Open questions, recorded rather than resolved

- **K4 under ATIPPA.** Newfoundland and Labrador treats the passage of time since a death
  as a factor in the section 40(5) weighing rather than as an exclusion from the
  definition. The NL configuration arguably should route K4 to escalation rather than to
  keep. It currently does not. This is a taxonomy question and it is open.
- **The K2 paragraph letters under ATIPPA.** The exception for a third party's position or
  functions exists in section 40(2); the paragraph letters were not confirmed against the
  consolidated text and are recorded as unverified. K2 is the code the whole over-redaction
  number turns on, so this is the largest open item in the NL mapping.

## The number this page is about

At the last full run, 41.2 percent of spans were escalated, and the escalation rate on the
must-redact category was 80.4 percent. That second figure is not a defect, it is the
current configuration: the model layer is off, so almost every third party the rules cannot
place lands here rather than being decided. Turning the model on is what moves it, and what
it costs in accuracy is the paired ablation that has not been run yet.

Regenerate both with `sever report`.
