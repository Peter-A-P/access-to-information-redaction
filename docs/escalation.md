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

### 7. A ranked member, in a sentence about their own life (`E1`)

Since 2026-10-17, in a record the Canadian Armed Forces produced, a person the record gives
a rank ("LCol Kromrey", "Gifford LCol SW@Deployed@KAF") is proposed for release as an
official (`K2`, rule `military_rank`), at the staff directory's confidence of 0.75 rather
than the 0.95 of a title in a signature block. A rank says the person is a member; it does
not say the sentence is about their work.

So the rule stands aside when the sentence is about the member rather than the job:
harassment, a complaint or grievance, a medical matter or an injury, a death or a memorial,
compassionate or sick leave, discipline, family. The span then falls through to case 1 and
is withheld. The word list is deliberately broad: "discipline" in "the CAN or US specific
training wrt discipline and finance" sends an officer doing their job to the reviewer, and
that is the cost of the guard, paid in reviewer time rather than in a stranger's file.

Outside a military record a rank means nothing to the rules. "Capt" in a fisheries record
is a ship's master, and a ship's master is a third party.

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
- **Whether a unique office identifies its holder.** A job title is released as K6: a
  position is not a person, and the privacy boundary already treats titles that way by
  refusing to substitute them. What that cannot see is the narrow real case, an office held
  by exactly one person in a small unit, where the title names them as surely as their name
  would. It is not a property of the word "Minister" and it is not detectable from the page,
  so it is left to the reviewer, who knows the organisation. Until 2026-09-21 the tool tried
  to cover it by escalating any title with a name in the same sentence, which withheld the
  word "Minister" about once a page and covered the real case only by accident.
- **A complaint party the phrasing does not reveal.** The parties to a confidential
  workplace complaint, and their job titles, are withheld (`complaint_party`, reviewer 1's
  ruling of 2026-10-10). The rule reads a record marked confidential that is about a
  workplace complaint, and a party is someone named in a sentence that says "the
  complainant", "the respondent", "the complaint was made by" or "the complaint names".
  One template in the corpus exercises it. A complaint file that names a party some other
  way, or a title the job-title recogniser only partly matches, reaches the rules behind
  it, which release a titled official, so a miss here is a leak and the reviewer is the
  backstop. The exception to the unique-office point above is this one: inside a
  complaint, the tool withholds the title rather than leaving it to the reviewer.
- **Handwriting.** Scanned typed documents only.
- **Nationality and religion words on their own.** "Canadian", "Afghan", "Muslim" come back
  from the detector as a nationality or religion and are escalated, because a person's
  national origin or religion is personal information when it is about an identifiable
  person. Alone, as in "Canadian Forces", it is about nobody. On the real-record track the
  detector's nationality-or-religion type is 37 escalations, 23 of them a form of
  "Canadian" and most of the rest French words or OCR noise it mistook for one. Whether the
  word is about someone is the reviewer's call for now.
- **Place names the detector reads as people.** "Kandahar" is a PERSON 19 times on the
  real-record track, counting "Aérodréme de Kandahar", and is withheld. A place gazetteer would fix it and is not built: a
  gazetteer that knew "Kandahar" would also know every town that is somebody's surname.
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

The NL configuration has since been scored: `sever report --jurisdiction nl`, in
[`results/nl/`](../results/nl/results.md). Two things came out of it.

The overrides change almost nothing on this corpus, because the rules never propose K3 or
K4 at all: `deceased_over_twenty_years` needs a date of death in the record and
`already_published` needs a public-register match, and on 210 documents neither fires.
Over-redaction reads 24.4 percent against the federal 23.2, and even that difference is the
denominator rather than behaviour, because 350 spans leave the must-keep pool. Leak rate,
escalation rate and recall are identical to the decimal.

What the 350 spans are doing instead is the finding. They are not being escalated, they are
being released under some other keeping code: **89.7 percent of them (86.3 to 92.7)**. The
tool settles, by machine, a question ATIPPA assigns to the head of a public body, and until
`unweighed_release_rate` existed no published number could see it, because `must_redact` is
REDACT, `must_keep` is KEEP, and a span whose true decision is escalate was in neither
denominator.

**That figure was 78.9 percent on 2026-09-20 and the job-title change moved it to 89.7**,
which is worth stating because the change was an unambiguous improvement federally and made
this worse. The released spans break down as 40 labelled K3 released as K6, 40 labelled K3
released as K2, and 11 labelled K4 released as K6. The first group is the one the change
touched: a public figure's title used to be escalated by a guard that was wrong for other
reasons, and is now released as "not information about an identifiable individual", which
is correct federally, where K3 releases anyway, and wrong here, where ATIPPA has no general
publicly-available exception.

The jurisdiction override cannot reach it. That machinery changes what a *code* decides, and
here the tool is not proposing K3 at all; it is proposing K6 about a span the ground truth
says is a person's public information. So this is a labelling problem wearing a decision
problem's clothes, for the third time in this project, and no rule can fix it from where the
rules stand.

Every headline figure in the README remains the federal configuration and none of them
moved.

## The number this page is about

At the last full run, **25.7 percent** of spans were escalated with the model layer on, and
**41.2 percent** with the rules alone. Both fell on 2026-09-21 when the rules stopped
escalating bare job titles, which is the largest single move either figure has made and was
not a change to the escalation policy at all.

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
