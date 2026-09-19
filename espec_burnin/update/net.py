"""One way of opening an HTTPS connection, shared by the checker and the
downloader.

These were two code paths once, and only the checker had the certificate
fallback. On a machine whose trust store Python could not use, the check
found the new version and the download then failed on
CERTIFICATE_VERIFY_FAILED - the worst of both, because the user was told an
update existed and then told it could not be fetched. One opener, used by
everything that talks to GitHub, is what stops that happening again.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


def open_url(request, timeout: float):
    """Open the request, falling back to certifi if the system trust store fails.

    The system store is tried first on purpose: a corporate proxy that
    intercepts TLS installs its own CA there, and certifi would reject it.
    certifi is the fallback for a frozen build whose system store is unusable,
    which is the common case on a locked-down Windows machine.
    """
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as exc:
        import ssl

        if not isinstance(exc.reason, ssl.SSLError):
            raise
        try:
            import certifi
        except ImportError:
            raise exc from None
        log.info("system trust store rejected the connection; trying certifi")
        context = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(request, timeout=timeout, context=context)
