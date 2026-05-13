# Security Overview

Hitchhiker is designed to handle confidential data over Signal with high security
guarantees. This document summarizes the framework's security features at a glance. For
the full threat catalog (19 threats, 60+ hardening items), see [THREAT_MODEL.md](THREAT_MODEL.md).

## Encryption

- **End-to-end encryption** — all message content is protected by Signal's E2E
  encryption between users and the VPS; plaintext only exists inside the Docker network
- **Encryption at rest** — Signal keys, session data, and Grist documents are stored on
  LUKS-encrypted volumes, inaccessible without the passphrase when the VPS is off or
  the volume is locked

## No Message Logging

- The bot processes messages **in memory only** and never writes message content to disk
- In group chats, messages that don't @-mention the bot are discarded before processing
- **Docker logging is disabled** (`driver: none`) on all containers — no log data is
  written to disk, eliminating the risk of accidental data retention in container logs
- The optional Caddy reverse proxy discards access logs entirely

## Network Isolation

- All services bind to **127.0.0.1 only** — nothing is exposed to the network except
  the optional Caddy reverse proxy (ports 80/443)
- Internal container communication stays within the Docker bridge network
- Remote admin access defaults to SSH tunnels; public access requires explicit Caddy
  setup with automatic TLS

## Authentication & Access Control

- **Admin access** — multi-user OIDC authentication via Dex with bcrypt-hashed
  passwords; Grist enforces per-document roles (Viewer, Editor, Owner) and tracks all
  changes per user
- **Bot access** — the bot has no authentication layer by design (any Signal user can
  query it); abuse is mitigated by per-sender rate limiting and @-mention filtering in
  groups

## Input Validation

- Grist API queries use **parameterized `args`** to prevent SQL injection from
  user-supplied message content
- Per-sender **sliding-window rate limiting** (default: 10 messages per 60 seconds)
  prevents flooding

## Container Hardening

- Compatible with **rootless Docker** — containers run in an unprivileged user
  namespace, eliminating most container-escape risks. LUKS setup still requires
  `sudo`, but Docker itself needs no root privileges.
- Slim base image (`python:3.14-slim`) with non-root user (`1000:1000`)
- Pinned dependency versions in `pyproject.toml`
- Docker logging disabled (`driver: none`) on all containers
- Grist telemetry disabled (`GRIST_TELEMETRY_LEVEL=off`)

## Secrets Management

- `.env`, `dex-config.yaml`, strategy files, and the LUKS volume image are all excluded
  from version control via `.gitignore`
- Secrets are injected via environment variables, never hardcoded in source
