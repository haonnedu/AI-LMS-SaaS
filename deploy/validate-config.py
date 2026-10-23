#!/usr/bin/env python3
"""Validate resolved Compose input without echoing secrets. Also usable locally."""
import json
import re
import sys
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise ValueError(message)


try:
    config = json.load(sys.stdin)
    require(config['name'] == 'eduvia-staging', 'Wrong project name')
    services = config['services']
    db_env = services['db']['environment']
    passwords = [db_env[key] for key in ('POSTGRES_PASSWORD', 'DB_MIGRATOR_PASSWORD', 'DB_RUNTIME_PASSWORD')]
    passwords.extend([services['redis']['environment']['REDIS_PASSWORD'], services['sessions']['environment']['REDIS_PASSWORD']])
    require(all(re.fullmatch(r'[0-9a-f]{64}', value) for value in passwords), 'Generate 32-byte hex DB/Redis passwords with generate-env.py')
    require(len(set(passwords)) == 5, 'DB and Redis credentials must be distinct')
    backend_env = services['api']['environment']
    require(backend_env['APP_ENV'] == 'production', 'APP_ENV must use supported production mode')
    origins = json.loads(backend_env['CORS_ORIGINS'])
    require(isinstance(origins, list), 'CORS_ORIGINS must be a JSON list')
    for origin in origins:
        parsed = urlsplit(origin)
        require(parsed.scheme == 'https' and parsed.hostname and not any((parsed.path, parsed.query, parsed.fragment, parsed.username, parsed.password)) and '*' not in origin, 'CORS origins must be exact HTTPS origins')
    require(config['networks']['data']['internal'], 'Data network must be internal')
    require(not any(network.get('external') for network in config['networks'].values()), 'External networks are forbidden')
    require(config['networks']['session']['internal'], 'Session network must be internal')
    require(set(services['sessions']['networks']) == {'session'}, 'Sessions must be isolated')
    for name in ('db', 'redis'):
        require(not services[name].get('ports'), 'Data ports must not be published')
        require(set(services[name]['networks']) == {'data'}, 'Data services must only use the private network')
    for name, service in services.items():
        if name != 'frontend':
            require(not service.get('ports'), 'Only frontend may publish a port')
    ports = services['frontend']['ports']
    require(len(ports) == 1 and ports[0]['host_ip'] == '127.0.0.1' and str(ports[0]['published']) == '3100' and ports[0]['target'] == 3000, 'Frontend must bind only loopback 3100')
    require(set(services['frontend']['networks']) == {'app', 'session'}, 'Frontend uses app and isolated session networks only')
except (ValueError, KeyError, TypeError) as exc:
    # Never include raw JSON or exception values (which can contain credentials).
    print('Staging configuration validation failed. Check required secrets, origins, project and network/port restrictions.', file=sys.stderr)
    sys.exit(1)
print('Staging configuration validated (secrets suppressed).')
