#!/bin/sh
# Postgres entrypoint sources this on first initialization only.
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 --file /opt/eduvia/bootstrap.sql
