"""One way of opening an HTTPS connection, shared by the checker and the
downloader.

These were two code paths once, and only the checker had a certificate
fallback. On a machine whose trust store Python could not use, the check found
the new version and the download then failed on CERTIFICATE_VERIFY_FAILED -
the worst of both, because the user was told an update existed and then told it
could not be fetched.

The fallback itself was then the next problem. It only ran *after* a failure,
and only when that failure arrived as an ssl.SSLError, so every connection to a
host Windows had not cached a root for cost a doomed attempt first - and any
failure that did not present as an SSLError skipped the retry entirely.
Windows fills its root store on demand rather than shipping it complete, so
that is the normal case on a chamber PC, not an unusual one.

So there is no fallback any more: one context carries the machine's own roots
*and* the bundle we ship, and every request uses it. A company proxy's CA lives
in the machine store and still works; a root Windows has never fetched comes
from the bundle; neither needs a failure first.
"""

from __future__ import annotations

import logging
import ssl
import urllib.request
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def trust() -> ssl.SSLContext:
    """The machine's certificate store, plus the one we ship.

    Built once: reading both stores costs milliseconds, and an update check
    runs on a timer.
    """
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        log.warning(
            "certifi is not in this build; only the machine's own certificate "
            "store is available and some hosts may be rejected"
        )
        return context

    try:
        # Adds to the roots already loaded rather than replacing them, so a
        # company proxy's own CA keeps working.
        context.load_verify_locations(cafile=certifi.where())
    except (OSError, ssl.SSLError) as exc:
        log.warning("could not load the bundled certificates: %s", exc)
    return context


def open_url(request, timeout: float):
    """Open the request against both certificate stores."""
    return urllib.request.urlopen(request, timeout=timeout, context=trust())
