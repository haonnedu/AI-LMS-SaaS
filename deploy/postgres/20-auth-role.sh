#!/bin/sh
set -eu
: "${DB_AUTH_PASSWORD:?Set the dedicated auth database password}"
psql --username "${POSTGRES_USER:-postgres}" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 --file /opt/eduvia/auth-role.sql
