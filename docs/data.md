# Data: what this repository uses, and where it came from

Public data only. No real personal information, nothing from any employer's systems, and
nothing internal to any public body. This page is the record of that, and it is kept
current in the same commit as any change to what the project reads.

## What is in the repository right now

| Source | What it is | Size | Terms |
|---|---|---|---|
| Generated personas and documents | Invented people rendered into six document templates written for this project | 210 pages, 5,355 labelled spans | Written here. No real person |
| Consolidated statute texts | Section numbers and quoted provisions in `sever/taxonomy/*.yaml` | 4 statutes, 33 provisions | Public legislation; each quote records the URL it was read from and the date |

Nothing else. The published-federal-releases track and the scanned track are planned in
`PLAN.md` and have not been built, so no third-party document has been fetched into this
repository and no fetcher exists yet.

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

## Planned, not present

`PLAN.md` describes two further sources. Neither has been fetched and neither has a loader.

- **Published completed federal access-to-information releases**, 60 to 100 pages sampled
  across departments, as the real-record over-redaction test. Everything visible in a
  released record was judged releasable by a human, which makes a visible span a genuine
  must-keep label. What sits under the existing black boxes cannot be recovered and is not
  a label at all, so leak rate is not computable on that track. The evaluation refuses to
  compute it rather than reporting a number that means nothing
  (`sever/eval/confusion.py::Scored.leak_rate`).
- **A scanned track**, corpus pages rasterised with noise and skew and read back through
  OCR, with the character error rate measured and reported separately.

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
