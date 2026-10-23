#!/usr/bin/env python3
"""Create a new private env file; never overwrite or print generated credentials."""
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit

if len(sys.argv) != 3:
    raise SystemExit('Usage: python3 deploy/generate-env.py /absolute/shared/staging.env https://staging.example.com')
target = Path(sys.argv[1])
origin = sys.argv[2]
parsed = urlsplit(origin)
if not target.is_absolute():
    raise SystemExit('Use an absolute env path outside the release directory')
if origin != '--tunnel' and (parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
    raise SystemExit('Supply an exact HTTPS origin without a trailing slash')
values = {key: secrets.token_hex(32) for key in (
    'POSTGRES_PASSWORD', 'DB_MIGRATOR_PASSWORD', 'DB_RUNTIME_PASSWORD', 'REDIS_PASSWORD', 'SESSION_REDIS_PASSWORD', 'AUTH0_SECRET', 'SESSION_ENCRYPTION_KEY'
)}
values['APP_BASE_URL'] = '' if origin == '--tunnel' else origin
values['CORS_ORIGINS'] = json.dumps([] if origin == '--tunnel' else [origin], separators=(',', ':'))
# Storage is unconfigured: an empty endpoint fails closed if the unused factory is called.
values.update(S3_ENDPOINT_URL='', S3_REGION='us-east-1', S3_BUCKET='eduvia-staging-unconfigured', S3_ACCESS_KEY_ID='', S3_SECRET_ACCESS_KEY='')
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
    stream.write('# Generated staging secrets. Do not commit, log, or source this file.\n')
    for key, value in values.items():
        stream.write(f"{key}='{value}'\n")
print('Created private env file. Object storage remains unavailable until configured.')
