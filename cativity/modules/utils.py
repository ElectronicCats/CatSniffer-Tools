import sys
from traceback import format_exception

class TrivialLogger:
    def _log(self, msg, *args, exc_info=None, **kwargs):
        msg = msg % args
        print(msg, file=sys.stderr)
        if exc_info:
            if isinstance(exc_info, BaseException):
                exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
            elif not isinstance(exc_info, tuple):
                exc_info = sys.exc_info()
            exc_str = ''.join(format_exception(*exc_info))
            print(exc_str, file=sys.stderr)

    debug = _log
    info = _log
    warning = _log
    error = _log
    critical = _log
    exception = _log

class UsageError(Exception):
    pass
class SerialError(Exception):
    pass


def fmt_addr_to_hex(addr):
    hex_addr = f"{addr:016x}"
    formatted_address = ':'.join(hex_addr[i:i+2] for i in range(0, len(hex_addr), 2))
    return formatted_address