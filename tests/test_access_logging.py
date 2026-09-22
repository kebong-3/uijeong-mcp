"""Real Uvicorn formatter regression; all credentials are synthetic."""
import logging
import sys

from uvicorn.logging import AccessFormatter
from runtime_security import SecretFilter


def test_access_formatter_keeps_arguments_and_masks_credentials(monkeypatch):
    monkeypatch.setenv('UIJEONG_BEARER_TOKEN', 'synthetic-secret')
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1,
        '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1:1234', 'POST', '/mcp?token=synthetic-secret&key=other-secret', '1.1', 401), None)
    for _ in range(2):
        assert SecretFilter().filter(record)
    assert len(record.args) == 5 and record.args[-1] == 401
    formatter = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    output = formatter.format(record)
    assert '401' in output and 'POST /mcp?' in output
    assert 'synthetic-secret' not in output and 'other-secret' not in output
    assert '[REDACTED]' in output
    assert 'synthetic-secret' not in logging.Formatter().format(record)


def test_regular_mapping_log_and_exception_are_redacted():
    try:
        raise ValueError('Bearer synthetic-secret')
    except ValueError:
        record = logging.LogRecord('httpx', logging.ERROR, '', 1,
            'request %(url)s', ({'url': 'https://example.test/?access_token=secret'},), sys.exc_info())
    assert SecretFilter().filter(record)
    output = logging.Formatter().format(record)
    assert 'secret' not in output and 'ValueError' in output
    assert record.exc_info is None and record.args == ()
