"""Reading a page's structure back from its text.

A scan and a released PDF carry no blocks, and until 2026-10-17 every paragraph of both was
BODY. That cost twenty points of over-redaction on the scanned track, because the rules
lean hardest on the signature block and the letterhead. These tests hold what the recovery
reads, and, as much, what it must not: the direction that costs a requester is a name read
into a signature block it was never in, which releases it as an official's.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sever.corpus.generate import Corpus
from sever.eval.layout import flattened, recovered
from sever.ingest.document import BlockKind, Page
from sever.ingest.layout import recover_blocks


def kinds(text: str) -> list[tuple[BlockKind, str]]:
    return [(b.kind, b.text) for b in recover_blocks(text)]


def kind_of(text: str, needle: str) -> BlockKind:
    for b in recover_blocks(text):
        if needle in b.text:
            return b.kind
    raise AssertionError(f"{needle!r} is in no block")


def test_every_block_is_the_slice_of_the_page_it_claims() -> None:
    text = "Department of Health\nOffice of the Minister\n\nDear Ms Tulk:\n\nBody text.\n"
    page = Page(number=1, text=text, blocks=recover_blocks(text))

    for b in page.blocks:
        assert page.slice(b.offsets) == b.text


def test_a_closing_word_and_the_lines_under_it_are_a_signature() -> None:
    text = (
        "Portions of the records have been withheld under the Act, as set out below.\n\n"
        "Sincerely,\n\nHugh Skinner\nSenior Policy Analyst\n709-555-1907\n"
    )

    blocks = [b for b in recover_blocks(text) if b.kind is BlockKind.SIGNATURE]

    assert len(blocks) == 1, "the closing and the name are one block, as rendered"
    assert "Hugh Skinner" in blocks[0].text and "709-555-1907" in blocks[0].text


def test_a_name_with_a_rank_under_it_is_a_signature_without_a_closing_word() -> None:
    """How a printed Outlook message from the forces signs off, with no blank line before
    it because the OCR text layer has none."""
    text = (
        "If you have any concerns about the process, please let them be known to me.\n"
        "Chris McGuffin\nLCol (OF-4)\nCO/J6 TFK HQ & Sig Sqn\n"
    )

    assert kind_of(text, "Chris McGuffin") is BlockKind.SIGNATURE


def test_a_name_alone_on_a_line_is_not_a_signature() -> None:
    """The dangerous direction. A name on a line of its own with nothing under it that is
    a title is a correspondent's address, a list, or a heading, and it stays BODY."""
    text = "Colm Quirke\n157 LeMarchant Road\nMount Pearl, NL A1N 4V6\n\nDear Colm Quirke:\n"

    assert kind_of(text, "157 LeMarchant") is BlockKind.BODY
    assert kind_of(text, "Dear Colm") is BlockKind.SALUTATION


def test_a_long_line_ends_a_signature() -> None:
    text = (
        "Gerald Yetman\nPolicy Analyst\n"
        "The rest of this line is prose that runs well past the length of a signature line.\n"
    )

    assert kind_of(text, "Gerald Yetman") is BlockKind.SIGNATURE
    assert kind_of(text, "The rest of this line") is BlockKind.BODY


def test_an_email_header_with_values_on_their_own_lines() -> None:
    """A printed Outlook header as OCR reads it back: each label on a line of its own."""
    text = (
        "From: \nKwasny Maj CS@CEFCOM HQ@Ottawa-Hull\nSent: \nThursday, 26 August 2010\n"
        "To: \nGifford LCol SW@Deployed@KAF\nCe: \nRoberge Maj JPJD@Deployed@KAF\n"
        "Subject: \nRecommendation\nSir,\n"
    )

    header = [b for b in recover_blocks(text) if b.kind is BlockKind.EMAIL_HEADER]

    assert len(header) == 1
    assert "Gifford LCol" in header[0].text, "the value under To: is part of the header"
    assert "Roberge" in header[0].text, "OCR's 'Ce:' is Cc"


def test_a_memorandum_header_is_not_an_email_header() -> None:
    """To, From, Date and Subject with no Sent line and no address. The corpus renders it
    as body text, and a recovery that disagreed would change what the rules see."""
    text = (
        "To: Desmond Okonkwo, Director of Operations\nFrom: Bernadette Halleran, "
        "Program Officer\nDate: 11 May\nSubject: Complaint\n"
    )

    assert all(kind is BlockKind.BODY for kind, _ in kinds(text))


def test_a_letterhead_opens_with_a_public_body_and_nothing_else_is_one() -> None:
    with_body = "Newfoundland and Labrador Health Services\nOffice of the Deputy Minister\n"
    with_person = "John Smith\nSmith Services Ltd\n12 Water Street\n"

    assert kind_of(with_body + "\nBody.", "Office of the") is BlockKind.LETTERHEAD
    assert kind_of(with_person + "\nBody.", "John Smith") is BlockKind.BODY


def test_a_page_the_recovery_cannot_read_is_paragraphs_of_body() -> None:
    """Toward BODY when unsure: what every page was before this module existed."""
    text = "ae w\n2 2\n50 .\n_ (Sy\naa 9\n\n= 5 INSTRUCTIONS\n"

    assert {k for k, _ in kinds(text)} <= {BlockKind.BODY, BlockKind.HEADING}


@pytest.mark.parametrize("variant", ["flattened", "recovered"])
def test_the_variants_change_the_blocks_and_never_the_text(corpus: Corpus, variant: str) -> None:
    make = flattened if variant == "flattened" else recovered
    for item in corpus:
        native = item.rendered.document
        other = make(native)
        assert [p.text for p in other] == [p.text for p in native]


def test_on_the_corpus_every_signature_and_header_label_is_recovered(corpus: Corpus) -> None:
    """Every labelled span the renderer put in a signature block or an email header is in
    one after recovery. Measured over the whole corpus in results/layout.md; held here on
    the session corpus so a regression fails CI rather than a report."""
    for item in corpus:
        native = item.rendered.document
        back = recovered(native)
        for span in item.rendered.labels.spans:
            truth = native.page(span.page).block_at(span.offsets)
            if truth is None or truth.kind not in (BlockKind.SIGNATURE, BlockKind.EMAIL_HEADER):
                continue
            got = back.page(span.page).block_at(span.offsets)
            assert got is not None and got.kind is truth.kind, (item.doc_id, span.text)


def test_recovery_never_promotes_a_must_redact_span_into_a_role_bearing_block(
    corpus: Corpus,
) -> None:
    from sever.taxonomy.loader import Decision, default_taxonomy

    taxonomy = default_taxonomy()
    for item in corpus:
        native = item.rendered.document
        back = recovered(native)
        for span in item.rendered.labels.spans:
            if taxonomy[span.code].decision is not Decision.REDACT:
                continue
            truth = native.page(span.page).block_at(span.offsets)
            got = back.page(span.page).block_at(span.offsets)
            was = truth.kind.is_role_bearing if truth else False
            now = got.kind.is_role_bearing if got else False
            assert was or not now, (item.doc_id, span.text, got.kind if got else None)


def test_flattening_is_what_the_scan_track_used_to_do(corpus: Corpus) -> None:
    from sever.ingest.ocr import paragraph_blocks

    native = corpus.items[0].rendered.document
    page = native.page(1)

    assert flattened(native).page(1).blocks == paragraph_blocks(page.text)
    assert replace(page, blocks=recover_blocks(page.text)).blocks
