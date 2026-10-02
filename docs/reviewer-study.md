# Running the reviewer study

The study measures reviewer minutes per page with the tool's proposals and without them,
and how accurate each arm was. It is the one result in this repository that a program
cannot produce. This page is everything the person running it needs.

## What you need

- This repository installed (`uv sync --extra detect --group dev`, then
  `python -m spacy download en_core_web_lg`), on one laptop.
- Two to four people, about an hour each. Four is the design: it balances which records
  each person sees with proposals and which arm they do first. Two gives a paired result.
  One gives timings but no paired comparison.
- No access-to-information experience is required. Experienced analysts make the result
  stronger, and the report does not record who anyone is.

## For each person

1. Run `sever study`. The browser opens on a welcome page that explains the task.
2. Hand them the laptop. They read the welcome page and press Start.
3. When they finish, the screen says so. Press Ctrl+C in the terminal.

The next person runs `sever study` again; it starts reviewer 2 automatically. If someone
stops halfway, running `sever study` again resumes them where they stopped. A page that
was open when the server stopped is timed again from when it reopens.

`sever study status` shows who has done how much. `sever study --reviewer 2` resumes a
particular reviewer, and `sever study --new` starts the next one even if the last did not
finish.

## Afterwards

Run `sever study report`. It scores every completed page against the corpus labels,
writes `results/reviewer-study.jsonl` and builds `results/reviewer.md` from that file
alone. Commit both. The raw audit logs and timings stay in `review/study/`, which is not
committed.

## What each person does

Twenty-two one-page records in two halves. One half shows the tool's proposals, and the
reviewer accepts or overrules each one and adds anything it missed. The other half has no
proposals, and the reviewer selects everything that must be withheld themselves. Each half
starts with a practice page that is not counted. Every page shows who made the request,
and a folded reference lists the release rules and the public register, so both arms work
from the same facts.

## Why it is built this way

- **Nobody sees a record twice.** Reviewing the same letter twice measures memory.
- **The halves swap between reviewers 1 and 2**, so every record is reviewed in both arms
  by someone, and the comparison can hold the documents fixed.
- **The order swaps between reviewers 1 and 2 and reviewers 3 and 4**, because the first
  half is always slower while people learn the screen.
- **Accuracy sits beside speed.** An arm that is fast because the reviewer accepted
  everything unread is measuring trust, not help. The table also shows the tool's
  unreviewed proposals on the same records, so it says whether reviewers improved on the
  tool or only rubber-stamped it.
- **Withholding text no label covers is counted separately.** The labels mark names,
  contacts and identifiers, not words like "sibling" beside a severed name, so
  withholding those is neither a leak nor an over-redaction. It still costs the reviewer
  time and the requester text, so the report shows it per page, for each arm and for the
  tool. Added after the first reviewer asked whether to withhold "sibling" as well.
- **Reviewers are numbers.** No name is written to any file.

The records come from the corpus test split, chosen by a fixed seed and balanced across
the six document types: `sever.review.study.study_pool`.
