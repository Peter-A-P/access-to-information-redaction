"""The committed model answers carry nothing about a persona.

`results/model-answers.jsonl` is the model's reply to every span of the paid corpus run,
committed so that the threshold sweep is reproducible without a gateway, a key or a cent.
That makes it published data in a public repository, so it gets the same treatment as an
outbound request: checked against the personas, which are ground truth, rather than
against the detector that produced the placeholders.

The risk is real and specific. The model is asked to quote the evidence it relied on, and
a model that had been shown a name could quote it back. Everything it sees is substituted
before the request is built, so it has no name to quote. This test is what says so about
the file that is actually on disk, rather than about the code path that wrote it.

It is skipped when the cache is absent, because the cache is produced by a run that spends
money and CI does not have a gateway. Where the file exists, the assertion is not
negotiable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sever.context.requester import normalise, normalise_identifier
from sever.corpus.generate import build

from .test_no_raw_entity_leaves import MIN_LENGTH, _persona_secrets

CACHE = Path("results/model-answers.jsonl")

# The cache was recorded over the published corpus, so the personas checked against it have
# to be the published corpus's, not a small fixture's. Checking twelve documents' personas
# against answers about two hundred and ten would pass while saying almost nothing.
PUBLISHED_DOCUMENTS = 210


@pytest.mark.skipif(not CACHE.is_file(), reason="no paid run has filled the answer cache")
def test_no_persona_value_appears_in_any_cached_model_answer() -> None:
    replies = [
        str(json.loads(line)["reply"])
        for line in CACHE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert replies, "the answer cache exists but is empty"

    secrets: set[str] = set()
    for item in build(documents=PUBLISHED_DOCUMENTS):
        secrets.update(_persona_secrets(item.rendered.cast))
    secrets = {s for s in secrets if len(s) >= MIN_LENGTH}

    body = "\n".join(replies)
    lowered = body.casefold()
    normalised = normalise(body)
    digits = normalise_identifier(body)

    offenders = []
    for secret in sorted(secrets):
        if secret.casefold() in lowered:
            offenders.append(f"{secret!r} appears literally")
            continue
        n = normalise(secret)
        if n and n in normalised:
            offenders.append(f"{secret!r} appears accent-normalised")
            continue
        d = normalise_identifier(secret)
        if len(d) >= 7 and d in digits:
            offenders.append(f"{secret!r} appears as digits")

    assert not offenders, (
        f"{len(offenders)} persona values are in the committed model answers, which are "
        f"published in a public repository:\n  " + "\n  ".join(offenders[:20])
    )


@pytest.mark.skipif(not CACHE.is_file(), reason="no paid run has filled the answer cache")
def test_every_cached_line_is_a_key_and_a_reply() -> None:
    """The cache is keyed by a hash of the request, so a line without a key is a line that
    can never be replayed and quietly turns into a fresh paid call."""
    for number, line in enumerate(CACHE.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        assert set(row) == {"key", "reply"}, f"line {number} has fields {sorted(row)}"
        assert len(row["key"]) == 64, f"line {number} is not keyed by a sha256"
