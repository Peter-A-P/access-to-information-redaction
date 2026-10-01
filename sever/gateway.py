"""Where `boundary` comes from, and which version of it will do.

`boundary` is project 04's library. It is not a declared dependency of this project and
cannot become one: it is not published to PyPI, and the name `boundary` on PyPI belongs to
an unrelated package that stops at 0.3.4. The source is public at
https://github.com/Peter-A-P/compliant-ai-gateway. A dependency line here does not fetch project
04; it fetches a stranger's package that happens to share the name. That is what the
`gateway` extra used to do, and CI resolving it is how it was found.

So the library is installed by path:

    uv pip install -e ../04-compliant-ai-gateway

and the version floor a dependency line would have bought is enforced here instead, at the
point of use. The floor is 0.23.0, and each release named below is a correctness fix this
project depends on rather than a preference for the newest thing:

  * **0.5.1** resolves an overlap by containment before score. Before it, Presidio's
    LOCATION "Bannerman Street" beat this project's ADDRESS "14 Bannerman Street" on score
    alone and the house number went into the released record. It also types the grouped
    health-number form that 07 measured leaking on 57 of 210 pages.
  * **0.5.3** refuses to rehydrate a document that already contains placeholder-shaped
    text, which could otherwise turn the literal string in a record into somebody's real
    name: a name in a released record that was never in the source.
  * **0.5.4** `Policy.outbound` refuses text carrying a placeholder it minted, so feeding
    its own output back is an error rather than a silent double substitution.
    `LayeredPolicy` in sever.detect.boundary_adapter is built not to do that and a test
    pins it.
  * **0.5.5** `Policy(spans, vault=...)` carries an earlier policy's placeholders into a
    rebuilt one. This closes a gap that only shows up across a rebuild or a process
    boundary, and it is narrower than it first looks: placeholders derived from the spans
    are minted identically by any policy over the same spans, so a rebuilt policy already
    refused and rehydrated those. What it could not carry is anything the *second pass*
    found, which is discovered while redacting and is not recoverable from the spans. So
    a rebuilt policy used to leave those placeholders in the text and resolve nothing,
    quietly. Nothing in this project rebuilds a policy today, which is why the gap was
    invisible here; the reviewer app will, because showing a reviewer what was sent means
    rehydrating in a different request than the one that redacted.
  * **0.6.0** masks an email address no recogniser claimed, including one spelled with
    accents. Before it, an address with no digit in it was neither identifier-shaped nor
    name-shaped and crossed `Policy.outbound` in clear. This project found the same class
    in its own scrub (the "email leak" amendment in PLAN.md) and fixed it there; the floor
    stops the layer underneath it from being the weaker of the two.
  * **0.6.2** lets a bracketed group join a code run, so `(709) 555-0199` is masked whole.
    Before it, `555-0199` was masked and the area code went out beside its own
    placeholder, and a bracketed area code is how a phone number is usually written.
  * **0.6.3** `Policy.second_pass` names the placeholders the fallback minted, which the
    entity type stopped saying once 0.6.0 minted `EMAIL` from the second pass. A leak
    decomposition that separates "the recogniser found it" from "only the backstop did"
    has to read this rather than the type.
  * **0.6.4** rehydrates a placeholder a model rewrote inside its brackets (a hyphen or a
    space for the underscore, a zero-padded index, a line break). Before it, those
    resolved to nothing and were listed in `unresolved`. `LayeredPolicy.rehydrate` passes
    straight through to this, and nothing here rehydrates model output today; the floor
    is set so that the first thing that does gets the values back.
  * **0.9.0** masks initials and surname particles with the name they belong to. Before
    it, `Mr M. Trznadel` went out as `Mr M. <NAME_LIKE_1>`, and `van der` sat in clear
    between two masked halves of a name. 04 found it on court judgments; the corpus here
    has no initials, which is a reason to take the fix rather than a reason to skip it.
  * **0.23.0** masks the rest of a value glued to a placeholder by `-`, `/` or `_` when
    it carries a digit. Before it, a file number half typed as an organisation sent its
    tail (`-1749`) to the wire. File numbers are the identifiers this project's own
    recognisers exist for, so this one reaches it directly. Nothing after 0.23.0 changes
    what `boundary.redact` masks (0.24 to 0.30 are measurement, caching and hosting).

Checked against 0.32.0, the version installed when the floor was raised on 2026-10-01:
the full suite passes, and `sever eval-detector --compare` was rerun on it. The 0.5.3 behaviour change 04 flagged (`Policy.outbound` refuses text carrying a
placeholder it minted) does not reach this project, because `LayeredPolicy` hands it source
text once and applies its own scrub afterwards; `tests/test_boundary_adapter.py` pins that.

All of them are the difference between a redaction that holds and one that leaks, so an
older `boundary` raises rather than running: an unmarked downgrade of the redaction is
exactly the failure this project is about. There is no upper bound to enforce, because
nothing pulls a newer one in by accident; a release of 04 that breaks this project breaks
a test, which is where that belongs.
"""

from __future__ import annotations

from typing import Any, Final

MINIMUM_BOUNDARY: Final = (0, 23, 0)

INSTALL: Final = "uv pip install -e ../04-compliant-ai-gateway"

BOUNDARY_MISSING: Final = (
    f"boundary, project 04's library, is not installed. It is not on PyPI, so clone "
    f"https://github.com/Peter-A-P/compliant-ai-gateway beside this repository and install "
    f"it by path: `{INSTALL}`. The `boundary` package on PyPI is an unrelated project and "
    f"is not this one."
)


class BoundaryUnavailable(RuntimeError):
    """Raised only where boundary is required and missing, or too old to be safe."""


def _parsed(version: str) -> tuple[int, ...]:
    """The leading numeric fields of a version, so that `0.5.4.dev1` compares as 0.5.4.

    A field that is not a plain integer ends the comparison rather than failing it: a
    suffixed build of 0.5.4 is treated as 0.5.4, which is the direction that does not
    refuse to run over a version string this function did not anticipate.
    """
    fields: list[int] = []
    for field in version.split("."):
        if not field.isdigit():
            break
        fields.append(int(field))
    return tuple(fields)


def installed_version() -> str | None:
    """The installed `boundary.__version__`, or None where it is not installed."""
    try:
        import boundary
    except ImportError:
        return None
    version = getattr(boundary, "__version__", None)
    return version if isinstance(version, str) else None


def require_boundary() -> Any:
    """Import `boundary` and check the floor, or raise `BoundaryUnavailable`."""
    try:
        import boundary
    except ImportError as exc:
        raise BoundaryUnavailable(BOUNDARY_MISSING) from exc

    version = installed_version()
    if version is None or _parsed(version) < MINIMUM_BOUNDARY:
        wanted = ".".join(str(n) for n in MINIMUM_BOUNDARY)
        raise BoundaryUnavailable(
            f"boundary {version or 'of an unreported version'} is installed, and this "
            f"project needs {wanted} or newer. The correctness fixes in between decide "
            f"whether a house number, a health number, an email address, an area code or "
            f"a rehydrated placeholder reaches a released record; see sever/gateway.py "
            f"for which. Update project 04 and "
            f"reinstall it: `{INSTALL}`."
        )
    return boundary


def available() -> bool:
    """True where a `boundary` new enough to be used is installed."""
    try:
        require_boundary()
    except BoundaryUnavailable:
        return False
    return True
