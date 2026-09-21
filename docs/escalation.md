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

The threshold is 0.90 and it is measured, not chosen: `results/thresholds.md` sweeps it
over one recorded set of model answers. On 2,606 answers, 43 percent clear 0.90 and the
rest land here. That is the single largest lever on this page, and the sweep shows why it
sits where it does: below 0.90 the leak rate is 10.9 percent, at 0.90 it is 5.3.

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

## Questions that were open, and what the statute said

All 36 provisions in the taxonomy are now verified against the consolidated texts, federal
on 2026-07-21 and ATIPPA on 2026-09-20. Reading them closed three questions and opened a
fourth, and none of the three closed in the direction that was guessed.

- **The K2 paragraph letters under ATIPPA** are **(f), (g) and (h)**, confirmed rather than
  guessed. This was the largest open item because K2 carries 2,345 of the corpus's 5,355
  spans. Paragraph (h) carries a limit the code does not encode: an opinion given in the
  course of performing services is released "except where they are given in respect of
  another individual", so an official's assessment of a member of the public is R1 and not
  K2. The tool cannot see that distinction and a reviewer has to.
- **K4 under ATIPPA** is decided, and it goes the way the open question suspected.
  Paragraph 40(5)(j) makes the time since a death a circumstance the head of a public body
  weighs and **states no period at all**, where the federal Act excludes an individual dead
  more than twenty years from the definition outright. A K4 that releases on a fixed number
  of years performs a weighing the Act reserves to a person, against a threshold this
  project invented. Under the NL configuration K4 escalates, and it does so in the code:
  `sever/taxonomy/nl.yaml` carries the override and `docs/taxonomy.md` prints it.
- **K3 under ATIPPA is narrower than anyone assumed**, and this one was not on the open
  list at all. There is **no general publicly-available exception** in the terms of the
  federal 19(2)(b). Paragraph 40(2)(m) releases two enumerated things only, attendance at a
  public event and receipt of an honour, and only where disclosure is not contrary to the
  public interest. A name that is already public for any other reason is not released by
  it. Under the NL configuration, anything K3 reaches through general "already public"
  reasoning escalates, and it does so in the code rather than only here.

The new question is what those three do to the NL numbers, and the honest answer is that
nobody knows yet: every published figure in this repository is from the federal
configuration, and the NL configuration has never been scored. Three codes moving toward
escalation would raise the NL over-redaction rate against the federal one, which is a
finding about the two statutes rather than about the tool. It is not measured and it is not
claimed.

## The number this page is about

At the last full run, **27.7 percent** of spans were escalated with the model layer on, and
**46.5 percent** with the rules alone.

The gap between those two columns is the whole argument of the model layer, and it is worth
reading in the right direction. The model does not make the tool decisive by being clever
about hard cases; it makes it decisive by answering 43 percent of the questions the rules
could not, and it is wrong on some of them. Escalation falls by 18.8 points and the leak
rate rises by 2.5. The reviewer's queue halves and a few more third parties are named in a
released record.

An earlier run escalated 46.1 percent with the rules alone, and both escalation figures rose
once when detection improved. That looks like a regression and is not. A better detector
finds more of the people in a record; the ones it newly finds are, by definition, the ones
the weaker detector missed, and they arrive with no title and no register entry attached. So
they escalate. The leak rate fell from 14.1 percent to 5.4 at the same time, which is the
trade this tool is designed to make: withhold and ask rather than release and hope.

Regenerate both with `sever report`.
