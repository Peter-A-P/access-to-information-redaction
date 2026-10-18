# Data: what this repository uses, and where it came from

Public data only. No real personal information, nothing from any employer's systems, and
nothing internal to any public body. This page is the record of that, and it is kept
current in the same commit as any change to what the project reads.

## What is in the repository right now

| Source | What it is | Size | Terms |
|---|---|---|---|
| Generated personas and documents | Invented people rendered into six document templates written for this project | 210 pages, 5,355 labelled spans | Written here. No real person |
| Consolidated statute texts | Section numbers and quoted provisions in `sever/taxonomy/*.yaml` | 5 statutes and regulations, 39 provisions (21 federal, 18 NL), every one verified | Public legislation; each quote records the URL it was read from and the date |

The scanned track renders and degrades the synthetic corpus itself, so it reads nothing
from outside. The published-federal-releases track reads six Library and Archives Canada
packages, 82 pages, downloaded once on 2026-10-01 and named in the committed manifest; the
PDFs themselves are not committed, and there is deliberately no fetcher (see below).

## The synthetic corpus

Everything in it is invented, and the invention is deliberate in ways worth stating.

- **Names** are drawn from fixed pools in `sever/corpus/personas.py`, chosen to look
  plausible for Newfoundland and Labrador correspondence. They are combinatorial draws from
  a forename list and a surname list; any resemblance to a specific living person is
  coincidence, and none of the pools was built from a real directory, register or record.
- **Telephone numbers** are all in the 709 area code with the 555 exchange, which is
  reserved for fiction.
- **Email addresses** use `example.com` and `gov.nl.ca.example`. The `.example` top-level
  domain is reserved by RFC 2606 and cannot be registered.
- **Street names** are real St. John's streets with invented house numbers. A street name
  is not personal information; the combination with an invented number and an invented
  person is not a real address.
- **Identifiers** (medical care plan numbers, social insurance numbers, employee numbers,
  file numbers) are generated in the right *shape* so the recognisers have something to
  find. They are not valid numbers and do not pass any checksum.
- **Roles are assigned before the document is written**, which is the whole point: see
  `sever/corpus/personas.py`. Every span's category follows from a decision made before any
  text existed, so the labels are known by construction.

The corpus is regenerated from a seed rather than committed:

```
sever corpus build --documents 210 --seed 20270802
```

Generated pages and labels are gitignored. The manifest, which carries a sha256 for every
page file and every label file, is not, so a published number can be tied to the exact
inputs that produced it without the inputs being in the repository.

## The legislation

Provisions are quoted from the consolidated texts, and every quote records where it was
read and when:

| Statute | Citation | Read from | Consolidation |
|---|---|---|---|
| Access to Information Act | R.S.C., 1985, c. A-1 | laws-lois.justice.gc.ca | current to 2026-07-21 |
| Privacy Act | R.S.C., 1985, c. P-21 | laws-lois.justice.gc.ca | current to 2026-07-21 |
| Access to Information and Protection of Privacy Act, 2015 | SNL 2015, c. A-1.2 | assembly.nl.ca | the page does not publish a consolidation date, and the YAML records `unknown` rather than inventing one |

Federal consolidated statutes are published by the Department of Justice under terms that
permit reproduction. The provincial Act is published by the House of Assembly. Neither is
reproduced here in bulk: what is quoted is the specific words each taxonomy code rests on,
which is the minimum needed for the citation to be checkable.

**18 of 33 provisions are verified against the consolidated text.** The rest are recorded as
unverified with the reason, and `docs/taxonomy.md` prints the count at the top. Nothing
defaults to verified. Run `sever taxonomy check` for the current list of unchecked rows.

## The public register

`sever/context/registers/` holds the published-officials lists that the K3 rule matches
against. The file shipped here is synthetic and exists to exercise the rule, not to be an
authority on who holds office. A public body points the configuration at its own published
lists. Every entry carries the source it was published in and the date it was read,
because "publicly available" is a claim that ends up in a redaction schedule and a claim in
a schedule needs a source.

The register is also extended, per document, with names printed on that record's own
letterhead. That extension is scoped to the one document on purpose: a name on this
letter's letterhead is published by the department in the act of writing the letter, and
carrying it into the register for every other record in the request would be an inference
rather than an observation.

## Published federal releases: six packages, 82 pages

The real-record over-redaction test. Everything still visible in a completed
access-to-information release was judged releasable by a public body's reviewer, which makes
a visible span a must-keep label that nobody in this project chose. What sits under the
existing black boxes cannot be recovered and is not a label at all, so leak rate is not
computable on that track and `sever/eval/confusion.py::Scored.leak_rate` refuses to compute
it rather than returning a number that means nothing.

**The source.** Library and Archives Canada publishes completed release packages for
archival records and serves them free of charge at
<https://telechargerdemandesaicompletees-downloadcompletedatirequests.bac-lac.gc.ca>. Other
federal institutions publish packages on their own sites. `open.canada.ca` publishes
*summaries* of completed requests, which are metadata and not records, and are no use for
this test.

**The terms, read 2026-09-21 at <https://www.canada.ca/en/transparency/terms.html>.**
Government of Canada material "may be reproduced in whole or in part for non-commercial
purposes, and in any format, without charge or further permission", subject to exercising
due diligence in ensuring accuracy, identifying the source, and not representing the
reproduction as an official version. Commercial redistribution needs written permission and
is not in scope here. This project is non-commercial, it reproduces nothing publicly in any
case, and it records the source URL of every package it measures.

**There is no fetcher, on purpose.** The LAC search runs on an undocumented endpoint behind
a JavaScript front end. Reverse-engineering it was attempted on 2026-09-21 and abandoned: it
is fragile, it is not a use the site documents, and a published number that depends on an
undocumented endpoint staying stable is not reproducible in the way the rest of this
repository is. So the track is manifest-driven. A person downloads packages,
`sever releases add` records each with its sha256, its source URL and the retrieval date,
and **the manifest is committed while the PDFs are not**. Anyone can download the same
packages from the same URLs and reproduce the number, or get a checksum failure naming the
file that differs.

**One guard before anything is scored.** A released PDF is supposed to have had the text
under its boxes removed, and not all of them do. A package that merely draws rectangles over
live text still carries the withheld names in its text layer, and this loader would read
them as visible and count every one as a must-keep label, marking the tool down for
proposing to redact exactly what the reviewer redacted. `inspect_redaction` checks for that
and excludes the package with a reason. It is the question `sever/eval/pdf_leak.py` asks of
this project's own exports, turned around and asked of somebody else's.

**The packages, 2026-10-01.** Six, all released by Library and Archives Canada from
Department of National Defence records (RG24), requests A-2025-03134 (four packages,
disclosed in part under s.19(1), 2008 to 2010) and A-2014-00356 (two, all disclosed, 2001):
82 pages. `data/releases/manifest.json` has each one's sha256, source URL, retrieval date
and details page. They were downloaded once, by hand-equivalent requests about two seconds
apart, with no fetcher written. LAC's own terms, read the same day at
<https://www.canada.ca/en/library-archives/terms-conditions.html>, allow non-commercial
reproduction without charge or permission with the title, author and source cited.

**Three things a reproducer needs to know.** The download URL in the manifest is LAC's
`sas-das` service, which answers with a staged link to the file; the file path alone
returns 403, so the manifest records the service URL, which is what the details page calls.
LAC re-OCRs its packages (these carry OCR dates of July and September 2026), so a later
re-OCR changes the bytes, and a checksum failure is then the honest outcome rather than a
fault. And no other federal institution was found serving release packages directly; the
others ask for a request to be made.

**The guard, extended for scans.** Every LAC package is one image per page with an
invisible OCR text layer and the boxes burned into the pixels, so `inspect_redaction` found
no vector rectangles and excluded all six as unchecked. `inspect_raster` now checks that
kind of package: structurally (one full-page image per page, no drawings, no visible text,
so the text layer can only be a reading of the image) and then in the pixels, finding the
solid boxes and reading the text layer inside each one. 106 boxes across the six packages,
none with a word under it. Its word threshold was chosen after looking at these packages,
which PLAN.md 12.32 says.

**These six are no longer a blind test (2026-10-17).** The military vocabulary in
`sever/detect/military.py` and the layout recovery in `sever/ingest/layout.py` were written
after reading what the tool withheld on these packages. The rank list is the Canadian Armed
Forces' own and does not depend on them; the list of units and headquarters, and the OCR
spelling of "Cc" as "Ce", came from them. `results/releases.md` scores the old and new
configurations over the same spans and says this above the table. A held-out check needs
more packages, ideally from another institution and another decade, scored once before
anything is changed in response. That check is the next section.

## Held-out releases: three packages, 83 pages, two other departments

`data/releases/heldout.json`, scored by `sever eval-releases --manifest
data/releases/heldout.json --held-out` into `results/releases-heldout.md`.

**The selection rule, written 2026-10-18 before anything was downloaded.** For each of three
record groups that are not Defence, RG29 (Health), RG25 (External Affairs) and RG76
(Immigration): walk LAC's search results for the record group newest request first, at most
the first 15 requests; from each request's details page take packages in listed order; a
package qualifies if its disposition is "Disclosed in part" and it has 3 to 40 pages; take
the first two that qualify per record group, at most one per request. Score every package
that passes the redaction guard once, with the code at commit `8e2b554`, and change nothing
in response before the number is published.

**What the rule gave.** RG29: none. Every one of its first 15 requests was either all
disclosed or longer than 40 pages, and the rule had no fallback, so Health is not in the set.
RG25: one, A-2026-01845, East German government, 1969 to 1990, 36 pages. RG76: two,
A-2026-03227 and A-2026-02957, Chinese immigration case files from 1913 to 1962, 36 and 14
pages. All three passed the guard (4, 6 and 10 boxes, none with text under them).

**How they were found.** Through LAC's own search page, as a browser uses it: the page's
anti-forgery token, its search request, then the details pages and the download service the
details page calls, about two seconds apart, about sixty requests in all. Nothing that did this is
committed, for 12.28's reasons; the manifest records each package's details page and download
URL, which is all a reproducer needs. The site's certificate chain ends in a Sectigo root the
macOS system bundle did not have, so the requests used the `certifi` bundle from the
project's environment rather than turning verification off.

## Planned, not present

`PLAN.md` describes one further source.

- **A scanned track**, corpus pages rasterised with noise and skew and read back through
  OCR, with the character error rate measured and reported separately. **Built and measured
  on 2026-09-20**; see `results/scanned.md`.

## The employer's own disclosure log is excluded, by decision

The Government of Newfoundland and Labrador publishes completed access-to-information
requests. That log is public, and it is still not used here. The reason is distance rather
than legality: this is a tool the employer wants and has not built, the public version is
built here in public, and any internal version would be built separately on the employer's
own tooling with no shared code in either direction. Using the employer's own disclosure
log would blur a line that is worth keeping visible. Published federal releases do the same
evaluation job.

## Rules that apply to any data added later

1. Public sources only, with the terms read and recorded in this file before the fetch.
2. No real personal information beyond what is already public in an already-released record.
3. Nothing raw is committed. Loaders fetch and verify checksums; the manifest is committed.
4. No credentials, and nothing from `.env`, ever.

## The fresh set: six packages, registered before the code that will be scored on them

`data/releases/fresh.json`. Written down, downloaded and checksummed on 2026-10-18, before
the archival age rule and the release-stamp screen were written, and committed before either
so the order is in the history rather than in a claim.

**The rule.** RG76 (Immigration), RG25 (External Affairs) and RG29 (Health): LAC's search
results newest request first, ranks 16 to 40, because the first 15 were the held-out set's
pool. RG18 (RCMP) and RG13 (Justice): ranks 1 to 25. From each request's details page,
packages in listed order; a package qualifies if it is "Disclosed in part" and has 3 to 40
pages; the first two per record group, at most one per request; a group with none
contributes none. The search returned one page of 28 to 41 requests per group and ranks
beyond it were not fetched.

**What it gave.** Two from Immigration (A-2026-01517, A-2026-01110), two from Health
(A-2026-00453, A-2025-06543), two found under Justice (A-2026-00638, and A-2025-04321, whose
package is an RG10 Indian Affairs audit report filed under the same request; the rule said
packages in listed order and did not say same record group, so it stands). None from
External Affairs ranks 16 to 28 or from RCMP. 132 pages. All six passed the redaction guard.

**How they will be scored.** Once with the code that adds the new rules, and once with
`48a1c4d` for comparison, into `results/releases-fresh.md`. Nothing is changed in response
before that table is published.
