"""Loopback-only v1 routes. Never downgrade a request to the legacy processor."""
import ipaddress
import json
import re
from urllib.parse import urlsplit

from kenradar.integrations.hermes_v1 import TASK_TYPE, ContractError, capabilities, receipt, retry, submit
from kenradar.web.responses import json_response

PREFIX = '/api/integrations/hermes/v1'


def dispatch(handler, path, method, config_path, data):
    if not path.startswith(PREFIX + '/'):
        return False
    database = None
    try:
        peer = handler.client_address[0]
        host = urlsplit('http://' + handler.headers.get('Host', '')).hostname
        origin = handler.headers.get('Origin')
        if (not ipaddress.ip_address(peer).is_loopback or host not in ('127.0.0.1', 'localhost', '::1')
                or (origin and origin != 'http://' + handler.headers.get('Host', ''))
                or handler.headers.get('Sec-Fetch-Site') == 'cross-site'):
            raise ContractError('LOOPBACK_REQUIRED', 'Only same-origin loopback access is permitted', 403)
        if path == PREFIX + '/capabilities' and method in ('GET', 'HEAD'):
            json_response(handler, capabilities())
            return True
        from kenradar.core.config import load_config
        from kenradar.storage import create_database
        config = load_config(config_path)
        if config.database_type != 'sqlite':
            raise ContractError('CAPABILITY_UNAVAILABLE', 'v1 requires SQLite')
        database = create_database(config)
        if method == 'POST':
            if handler.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                raise ContractError('INVALID_REQUEST', 'application/json is required')
            if isinstance(data, (bytes, bytearray)):
                try:
                    data = json.loads(data)
                except (ValueError, UnicodeError):
                    raise ContractError('INVALID_REQUEST', 'Invalid JSON') from None
        match = re.fullmatch(re.escape(PREFIX) + r'/tasks/([1-9][0-9]*)(/retry)?', path)
        if path == PREFIX + '/content-tasks' and method == 'POST':
            result, status = submit(database, data), 202
        elif match and method == 'POST' and match[2]:
            result, status = retry(database, int(match[1]), data), 202
        elif match and method in ('GET', 'HEAD') and not match[2]:
            row = database.get_task_run(int(match[1]))
            if not row or row['task_type'] != TASK_TYPE:
                raise ContractError('TASK_NOT_FOUND', 'Hermes task not found', 404)
            result, status = receipt(row, database), 200
        else:
            raise ContractError('INVALID_REQUEST', 'Unknown v1 endpoint or method', 404)
        json_response(handler, {'ok': True, **result}, status=status)
    except ContractError as exc:
        json_response(handler, {'ok': False, 'error': {'code': exc.code, 'message': str(exc)}}, status=exc.status)
    except Exception:
        json_response(handler, {'ok': False, 'error': {'code': 'INTERNAL_ERROR', 'message': 'Integration request failed'}}, status=500)
    finally:
        if database:
            database.close()
    return True
