#!/usr/bin/env python3
"""Offline structural checks; requires PyYAML. Does not replace Compose/DB smoke tests."""
import ast
import copy
import io
import json
from pathlib import Path
import runpy
import sys
import yaml

root = Path(__file__).resolve().parents[1]
config = yaml.safe_load((root / 'compose.staging.yaml').read_text())
for path in (root / 'deploy').glob('*.py'):
    ast.parse(path.read_text(), filename=str(path))
assert config['name'] == 'eduvia-staging'
assert config['networks']['data']['internal'] is True
assert not any(value.get('external') for value in config['networks'].values())
services = config['services']
assert set(services) == {'db', 'redis', 'migrate', 'api', 'worker', 'frontend'}
assert services['frontend']['ports'] == ['127.0.0.1:3100:3000']
for name, service in services.items():
    assert not service.get('network_mode')
    if name != 'frontend':
        assert not service.get('ports')
assert services['migrate']['environment']['DATABASE_URL'].startswith('postgresql+psycopg://eduvia_migrator:')
assert services['api']['environment']['DATABASE_URL'].startswith('postgresql+psycopg://eduvia_runtime:')
assert services['worker']['environment']['DATABASE_URL'] == services['api']['environment']['DATABASE_URL']
assert services['api']['environment']['APP_ENV'] == 'production'
# Simulate normalized `compose config --format json` to exercise the validator,
# using dummy values only. Real Compose expansion is a separate required test.
resolved = copy.deepcopy(config)
resolved['services']['db']['environment'].update(POSTGRES_PASSWORD='1'*64, DB_MIGRATOR_PASSWORD='2'*64, DB_RUNTIME_PASSWORD='3'*64)
resolved['services']['redis']['environment']['REDIS_PASSWORD'] = '4'*64
resolved['services']['api']['environment']['CORS_ORIGINS'] = '["https://staging.example.com"]'
resolved['services']['frontend']['ports'] = [dict(host_ip='127.0.0.1', published='3100', target=3000)]
previous = sys.stdin
try:
    sys.stdin = io.StringIO(json.dumps(resolved))
    runpy.run_path(str(root / 'deploy/validate-config.py'), run_name='__main__')
    resolved['services']['db']['ports'] = [dict(published='5432', target=5432)]
    sys.stdin = io.StringIO(json.dumps(resolved))
    try:
        runpy.run_path(str(root / 'deploy/validate-config.py'), run_name='__main__')
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError('Validator accepted published DB port')
finally:
    sys.stdin = previous
print('Offline staging structure, Python syntax and validator positive/negative tests passed.')
