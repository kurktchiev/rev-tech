# demo-postgres-db (192.168.1.253) — IPv6/Hostname Fix

**Date:** 2026-03-09

## Problem

After network issues, the `demo-postgres-db` hostname was resolving to an IPv6 address (`fd94:4508:defc:8ec3:be24:11ff:fe14:730d`) instead of a local IPv4 address. This caused Teleport's database agent to fail when connecting to PostgreSQL for auto-user-provisioning, since PostgreSQL wasn't listening on that IPv6 interface.

Additionally, PostgreSQL was only bound to a specific interface, not `localhost` or `0.0.0.0`.

## Root Cause

1. **`/etc/hosts` was missing the hostname** — it had `postgres-db` but not `demo-postgres-db`, so hostname resolution fell through to IPv6 (likely mDNS/SLAAC).
2. **PostgreSQL `listen_addresses`** was not set to `*` or `localhost`, so it only accepted connections on the external interface.

## Changes Made

### 1. `/etc/hosts` — added `demo-postgres-db` alias

```
# Before
127.0.1.1 postgres-db.homelab.local postgres-db

# After
127.0.1.1 postgres-db.homelab.local postgres-db demo-postgres-db
```

### 2. `/etc/postgresql/*/main/postgresql.conf` — listen on all interfaces

```
# Before
listen_addresses = '<specific IP>'

# After
listen_addresses = '*'
```

### 3. `/etc/teleport.yaml` — no net change

The `uri` was temporarily changed during debugging (`demo-postgres-db:5432` → `localhost:5432` → `127.0.0.1:5432`) but should be back to the original:

```yaml
uri: demo-postgres-db:5432
```

**Verify this is correct** — it may still be set to `127.0.0.1:5432` from debugging. If so, change it back to `demo-postgres-db:5432` so the TLS cert (issued for `demo-postgres-db`) matches.

## Services Restarted

- `sudo systemctl restart postgresql`
- `sudo systemctl restart teleport`
