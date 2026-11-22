"""Drop query values from access/HTTP logs, including legacy rejected tokens."""
import logging
import re

_QUERY = re.compile(r"([?&](?:session|token|access_token|api_key|t|s|password|key)=)[^&\s\"']+", re.I)


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = str(args[2]).split("?", 1)[0]
            record.args = tuple(args)
        record.msg = _QUERY.sub(r"\1[redacted]", record.getMessage())
        record.args = ()
        return True


def install() -> None:
    for name in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(name).addFilter(RedactSecrets())
