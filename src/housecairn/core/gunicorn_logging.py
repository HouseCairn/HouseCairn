"""gunicorn's logger, with the secret of a calendar feed masked in the access log.

Used as `--logger-class=housecairn.core.gunicorn_logging.Logger` by the entrypoint. A format
string cannot do this: it prints the request line as received. Every text atom is redacted, so
a custom `--access-logformat` (`%(U)s`, `%(r)s`, `{referer}i`...) is covered as well.
"""

from typing import Any

from gunicorn.glogging import Logger as GunicornLogger

from housecairn.core.log_redaction import redact_atoms


class Logger(GunicornLogger):  # type: ignore[misc]
    def atoms(self, resp: Any, req: Any, environ: Any, request_time: Any) -> dict[str, Any]:
        return redact_atoms(super().atoms(resp, req, environ, request_time))
