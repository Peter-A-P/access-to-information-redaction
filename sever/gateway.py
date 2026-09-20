"""Where `boundary` comes from, and which version of it will do.

`boundary` is project 04's library. It is not a declared dependency of this project and
cannot become one: it is a private repository, and the name `boundary` on PyPI belongs to
an unrelated package that stops at 0.3.4. A dependency line here does not fetch project
04; it fetches a stranger's package that happens to share the name. That is what the
`gateway` extra used to do, and CI resolving it is how it was found.

So the library is installed by path:

    uv pip install -e ../04-compliant-ai-gateway

and the version floor a dependency line would have bought is enforced here instead, at the
point of use. The floor is 0.5.4, and each release between 0.2 and it is a correctness fix
this project depends on rather than a preference for the newest thing:

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

All three are the difference between a redaction that holds and one that leaks, so an
older `boundary` raises rather than running: an unmarked downgrade of the redaction is
exactly the failure this project is about. There is no upper bound to enforce, because
nothing pulls a newer one in by accident; a release of 04 that breaks this project breaks
a test, which is where that belongs.
"""

from __future__ import annotations

from typing import Any, Final

MINIMUM_BOUNDARY: Final = (0, 5, 4)

INSTALL: Final = "uv pip install -e ../04-compliant-ai-gateway"

BOUNDARY_MISSING: Final = (
    f"boundary, project 04's library, is not installed. It is a private repository and "
    f"not on PyPI, so install it by path: `{INSTALL}`. The `boundary` package on PyPI is "
    f"an unrelated project and is not this one."
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
            f"project needs {wanted} or newer. Three correctness fixes in between decide "
            f"whether a house number, a health number or a rehydrated placeholder reaches "
            f"a released record; see sever/gateway.py for which. Update project 04 and "
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
