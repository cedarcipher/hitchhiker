# Threat Model — Signal Chatbot

This document identifies security concerns, attack surfaces, and mitigations for the
Signal chatbot service. The system is designed to handle **confidential data** and must
provide **high security guarantees**.

---

## Summary

The system consists of four Docker containers — a Signal REST API bridge, a Python
chatbot, a Grist spreadsheet database, and a Dex OIDC provider — deployed on a single
VPS behind an optional Caddy TLS reverse proxy. Signal users query the bot via
end-to-end encrypted messages; admins manage data through Grist's web UI, authenticated
via Dex.

**Primary attack surfaces**: (1) the unauthenticated Signal-facing bot endpoint, where
any user who knows the bot's number can send queries; (2) the publicly exposed Grist and
Dex web interfaces (ports 80/443 via Caddy), protected by single-factor OIDC passwords;
and (3) the VPS itself, accessible via SSH.

**Critical assets**: Signal private keys and session data (impersonation risk if leaked),
Grist document data (the confidential dataset), and secrets stored in `.env` and
`dex-config.yaml`.

**Key mitigations in place**:
- **Encryption at rest** — all sensitive data volumes (`signal-data`, `grist-data`) are
  backed by LUKS-encrypted loopback storage. When the VPS is powered off or the volume
  is locked, all stored data — including any contact metadata that signal-cli
  accumulates from group chats — is encrypted and inaccessible without the passphrase.
  This is especially important because the bot receives every message in groups it
  belongs to, and signal-cli automatically records sender phone numbers, group
  membership lists, and delivery metadata for all participants — not just those who
  interact with the bot directly
- **End-to-end encryption** — message content is never visible outside the Docker
  network; Signal's E2E encryption protects data in transit
- **No message logging** — the bot processes messages in memory only and never persists
  message content to disk, databases, or application logs. In group chats, the bot
  receives all messages from all participants, but discards any message that does not
  @-mention the bot before processing. Neither the content of matched nor unmatched
  messages is ever written to storage. Docker container logs are configured with
  `driver: none`, meaning no log data is written to disk. Even if a library unexpectedly
  logs message fragments, they are never persisted. The optional Caddy reverse proxy is also configured with
  `log { output discard }` to suppress access logs entirely
- **Localhost-only services** — all containers except Caddy bind to `127.0.0.1`,
  limiting network exposure
- **Per-sender rate limiting** — sliding-window throttling prevents message flooding
- **Parameterized queries** — Grist API calls use `args` to prevent SQL injection

**Residual risks**: signal-cli unavoidably retains PII (phone numbers, group membership,
delivery receipts) for all group participants — not just users who query the bot. This
data is protected by LUKS encryption at rest and disabled Docker logging, but exists in plaintext on the filesystem while the encrypted volume is unlocked.
Other residual risks include Grist's undo history retaining deleted data, single-factor
authentication on the public Dex endpoint, and the unauthenticated bot endpoint relying
solely on rate limiting for abuse prevention.

This threat model catalogs 19 threats (T1–T19) across these surfaces and provides a
60+ item hardening checklist for deployment.

---

## 1. System Boundaries & Trust Zones

```
 UNTRUSTED                      TRUSTED (VPS)
┌──────────┐               ┌──────────────────────────────────────────────────┐
│  Signal   │  E2E encrypted│  ┌───────────┐    ┌─────────────┐               │
│  Users    │◄─────────────►│  │ signal-api │◄──►│  Python Bot  │               │
│ (phones)  │               │  └───────────┘    └──────┬──────┘               │
└──────────┘               │       ▲                   │                      │
                            │       │                   ▼                      │
                            │  ┌────┴─────┐      ┌──────────┐  OIDC          │
                            │  │ Signal   │      │  Grist   │◄──►Dex         │
                            │  │ keys &   │      │ (Docker) │  (multi-user)  │
 SEMI-TRUSTED               │  │ sessions │      └─────▲────┘    ▲           │
┌──────────┐               │  └──────────┘            │         │            │
│  Admin   │  HTTPS/Caddy  │                    password login   │            │
│(browser) │──────────────►│                    (per-user via Dex)            │
└──────────┘               │                                                  │
                            │  Caddy (port 443) — public TLS for Grist + Dex  │
                            └──────────────────────────────────────────────────┘
```

| Zone     | Components                                | Trust level |
|----------|-------------------------------------------|-------------|
| Trusted  | VPS, bot process, signal-api, Grist, Dex  | High        |
| Semi-trusted | Admins via Caddy + Dex password or SSH tunnel (full Grist UI) | Medium — authenticated, per-user access via OIDC |
| Semi-trusted | Signal servers (relay encrypted msgs) | Medium — they see metadata but not content |
| Untrusted | Signal users sending messages to the bot | Low — input must be validated |
| Untrusted | The public internet (ports 80/443 via Caddy — Grist and Dex) | None        |

---

## 2. Assets to Protect

| Asset                        | Confidentiality | Integrity | Availability | Encrypted at rest? |
|------------------------------|:-:|:-:|:-:|:-:|
| **Signal private keys & session data** (`signal-data` volume) | CRITICAL | CRITICAL | HIGH | Yes (LUKS) |
| **Grist document data** (`grist-data` volume) | HIGH | HIGH | HIGH | Yes (LUKS) |
| **LUKS passphrase** (human knowledge) | CRITICAL | CRITICAL | HIGH | N/A |
| **Grist API key & OIDC client secret** (`.env`) | CRITICAL | CRITICAL | HIGH | No |
| **Dex config** (`dex-config.yaml` — password hashes) | HIGH | HIGH | MEDIUM | No |
| **Bot configuration** (`.env`) | HIGH | HIGH | MEDIUM | No |
| **Signal chat channel access** (group membership / phone number) | HIGH | HIGH | HIGH | N/A |
| **Admin session** (Caddy/SSH tunnel + Grist login) | HIGH | HIGH | MEDIUM | N/A |
| **Message content** (in transit — never at rest) | HIGH | MEDIUM | LOW | N/A |
| **Bot source code** (if proprietary) | MEDIUM | HIGH | LOW | No |

---

## 3. Threat Catalog

### T1 — Signal key material and PII compromise

**Risk**: CRITICAL
**Description**: If `signal-cli-config/` is exfiltrated, an attacker can impersonate the
bot's Signal identity, read all future messages, and decrypt any stored session data.

Beyond key material, `signal-cli-config/` also stores **personally identifiable
information (PII)**: phone numbers of all contacts who have messaged the bot, group
membership lists, delivery receipts with timestamps, and profile data (display names,
avatars). This data is created and managed by signal-cli — the bot framework has no
control over what is stored.

**Mitigations**:
- Signal data is stored in the `signal-data` Docker volume, which is backed by a
  LUKS-encrypted loopback file (see T13) — data is encrypted at rest
- The Docker volume is bind-mounted to the LUKS mount point (e.g., `/mnt/hitchhiker/signal`)
  — the data is accessible on the host filesystem while the encrypted volume is unlocked,
  but encrypted at rest when the volume is locked
- Never commit signal key material to version control
- Regularly audit VPS access logs for unauthorized SSH sessions
- Be aware that even with the bot deleted, the encrypted volume retains PII until
  the LUKS volume is securely wiped (destroy the key header)

### T2 — Exposed signal-cli-rest-api port

**Risk**: HIGH
**Description**: The signal-cli-rest-api exposes an unauthenticated REST API. If reachable
from the network, anyone can send messages, read contacts, and manage the Signal account.

**Mitigations**:
- Bind to `127.0.0.1` only (done in `docker-compose.yml`)
- Use SSH tunnel for initial QR code linking — never expose the signal-api port publicly
- Use Docker internal networking so only the `bot` container can reach `signal-api`
- Add a firewall rule (UFW/iptables) to block the signal-api host port from external
  access as defense in depth

### T3 — Grist API key leakage

**Risk**: HIGH
**Description**: `GRIST_API_KEY` in `.env` grants access to the Grist document. Leakage
via logs, error messages, container inspect, or version control exposes all spreadsheet
data.

**Mitigations**:
- Never commit `.env` — must be in `.gitignore`
- Use Docker secrets or a secrets manager (e.g., Vault) in production instead of env vars
- Ensure error handlers and logging never print the `GRIST_API_KEY` or full request headers
- Set file permissions: `chmod 600 .env`
- Use a read-only API key for the bot — the bot only needs `SELECT` access
- Grist's port (8484) is bound to `127.0.0.1` — publicly accessible only through Caddy,
  not directly

### T4 — Injection via Signal messages

**Risk**: HIGH
**Description**: Malicious users can send crafted messages that, when passed to the Grist
SQL endpoint, could result in SQL injection. Grist's `/api/docs/{docId}/sql` endpoint
accepts parameterized queries (`"args": [...]`), but only if the bot uses them correctly.

**Mitigations**:
- Always use Grist's parameterized `args` array — never interpolate message text into the
  SQL string
- Validate and sanitize input before it reaches the Grist client
- Apply a maximum message length check in the command handler
- The Grist client (`db.py`) must enforce parameterized queries in its interface contract
- Grist's SQL endpoint is read-only by design (only `SELECT` is allowed), which limits
  the blast radius of any injection that bypasses parameterization

### T5 — Denial of service via message flooding

**Risk**: MEDIUM (partially mitigated by per-sender rate limiting)
**Description**: An attacker could flood the bot with messages, exhausting CPU, memory, or
database connections. Caddy exposes both Grist and Dex publicly on ports 80/443, making
them additional DoS surfaces. Dex is particularly sensitive — auth endpoints are
computationally expensive due to bcrypt password hashing.

**Current status**: Partially mitigated. The bot now implements **per-sender rate limiting**
using a sliding window algorithm. Each sender (identified by Signal UUID) is allowed at
most `RATE_LIMIT_MAX` messages within a rolling `RATE_LIMIT_WINDOW` second period.
Excess messages are silently dropped. The rate limiter runs after @-mention filtering,
so unmentioned group messages do not consume a sender's allowance.

**Mitigations**:
- **Per-sender rate limiting** (implemented) — configurable via `RATE_LIMIT_MAX` and
  `RATE_LIMIT_WINDOW` environment variables (defaults: 10 messages / 60 seconds).
  Uses in-memory sliding window; tracks only UUIDs for privacy.
- Set connection/timeout limits on the Grist HTTP client
- Use Docker resource limits (`deploy.resources.limits` in compose) to cap CPU and memory
- Consider ignoring messages from unknown senders or non-whitelisted groups
- Add rate limiting in the Caddyfile (`rate_limit` directive) for both Grist and Dex

### T6 — Metadata exposure to Signal servers

**Risk**: MEDIUM
**Description**: Signal's end-to-end encryption protects message content, but Signal
servers can observe metadata: who messaged whom, when, message sizes, and online status.

**Mitigations**:
- This is an inherent limitation of the Signal protocol and cannot be fully mitigated
- Be aware that message timing patterns could reveal when database lookups occur
- If metadata privacy is critical, consider running the VPS behind a VPN or Tor (adds
  latency and complexity)

### T7 — Container escape / host compromise

**Risk**: MEDIUM
**Description**: A vulnerability in signal-cli-rest-api (Java/JVM), the Python runtime,
or Grist could allow container escape and host access. Caddy's Go runtime adds to the
attack surface.

**Mitigations**:
- **Use rootless Docker** — containers run in an unprivileged user namespace, so even a
  container escape only yields access to the unprivileged user, not root. The encrypted
  storage scripts support rootless Docker by `chown`ing the LUKS mount point to the
  invoking user (`SUDO_USER`).
- Run containers as non-root users (add `user: "1000:1000"` to compose services)
- Use read-only root filesystems where possible (`read_only: true` in compose)
- Keep base images updated — pin to specific versions and rebuild regularly
- Enable Docker's seccomp and AppArmor profiles (default in modern Docker)
- Minimize installed packages in the bot Dockerfile (already using `python:3.14-slim`)

### T8 — Logging sensitive data

**Risk**: MEDIUM
**Description**: Message content, database results, or credentials could end up in Docker
logs, syslog, or application log files. Chatbot interaction logs should not be retained.

Note: Grist's built-in document history intentionally tracks per-user changes for audit
attribution — this is a feature, not a leak. Enterprise-only audit log *streaming* is
not available in grist-core.

**Mitigations**:
- Never log message content or database query results at any level
- Use structured logging with explicit field filtering — operational events only
- All containers configured with `logging: driver: none` — no log data written to disk
- `GRIST_TELEMETRY_LEVEL=off` to prevent telemetry data leaving the VPS
- No external log aggregation — logs stay local and auto-rotate
- Access logs are disabled in the Caddyfile (`log { output discard }`) for both Grist and Dex

### T9 — Supply chain attacks (dependencies)

**Risk**: MEDIUM
**Description**: Malicious or compromised packages could execute arbitrary code inside the
bot container. PyPI packages (`signalbot`, `python-dotenv`, `httpx`, `pyyaml`) are the
primary risk.

**Mitigations**:
- Pin all dependency versions in `pyproject.toml` (exact versions, not ranges)
- Use `pip install --require-hashes` with a lock file for reproducible builds
- Audit dependencies periodically with `pip-audit` or `safety`
- Build images in CI with a hash-verified lock file — never install unverified packages
  in production
- Pin all Docker image tags — do not use `latest` in production

### T10 — Unauthorized VPS access

**Risk**: HIGH
**Description**: SSH compromise gives full access to all assets on the VPS. Caddy exposes
ports 80/443 publicly for Grist and Dex access, increasing the network attack surface.

**Mitigations**:
- Disable password authentication — SSH key only
- Use a non-standard SSH port
- Enable `fail2ban` to block brute-force attempts
- Enable unattended security updates (`unattended-upgrades` on Debian/Ubuntu)
- Consider a bastion host or VPN for SSH access
- Enable 2FA for SSH (e.g., `libpam-google-authenticator`)
- Firewall rules must explicitly allow only ports 80, 443, and SSH — all other ports
  must remain blocked

### T11 — Admin credential compromise (Dex)

**Risk**: HIGH
**Description**: Dex stores admin passwords as bcrypt hashes in `dex-config.yaml`. If
this file is exfiltrated, an attacker could offline-brute-force weak passwords and gain
Grist admin access (data read/write/delete). Since Dex is publicly accessible via Caddy,
a compromised password alone is sufficient to gain full Grist access — no SSH access is
required. Dex's public login endpoint is also exposed to online brute-force attacks.

**Mitigations**:
- Use strong passwords (16+ characters, randomly generated)
- Use a high bcrypt cost factor (10+ rounds, `htpasswd -nbBC 10`)
- Restrict file permissions: `chmod 600 dex-config.yaml`
- Never commit `dex-config.yaml` to version control (must be in `.gitignore`)
- Add rate limiting for Dex in the Caddyfile (`rate_limit` directive) to slow online
  brute-force attacks against the login endpoint
- Review `staticPasswords` entries periodically and remove stale accounts

### T12 — Accidental data retention via logs

**Risk**: MEDIUM
**Description**: Docker container stdout/stderr, Grist internal debug output, or Dex token
exchange logs could inadvertently persist sensitive data (message content, query results,
user activity) beyond what is intentionally tracked in Grist's document history.

**Mitigations**:
- All containers use `logging: driver: none` — Docker writes no log data to disk
- `GRIST_TELEMETRY_LEVEL=off` — no data sent to Grist Labs
- Grist audit log streaming is Enterprise-only and not available in grist-core
- Bot application code must never log message content, query results, or emoji reactions
- No external log aggregation services (Splunk, Datadog, etc.)
- Periodic verification: `docker compose logs` should contain only startup/health output

### T13 — Unencrypted data at rest

**Risk**: HIGH (mitigated by LUKS-encrypted Docker volumes)
**Description**: Neither Grist nor signal-cli encrypt data at rest at the application
layer. Grist stores documents as plain SQLite files. signal-cli stores key material and
PII as plain files. Without encryption, disk access (theft, decommissioning, hosting
provider access) exposes all data in cleartext.

**Current status**: **Mitigated.** Both Docker volumes (`signal-data` and `grist-data`)
are backed by a LUKS-encrypted loopback file (`hitchhiker.img`). The stack refuses to
start if the encrypted mount is not present. See `scripts/setup-encrypted-storage.sh`.

**Residual risks**:
- The LUKS passphrase must be entered manually after each reboot — there is no automated
  unlock (by design: automated unlock would defeat encryption)
- Files outside the encrypted volume (`.env`, `dex-config.yaml`, strategy files, Docker
  logs) are NOT encrypted by the volume-scoped LUKS
- If the VPS is compromised while running (volume mounted and unlocked), the attacker
  has access to decrypted data in memory and on the mounted filesystem
- Cloud provider disk snapshots taken while the volume is mounted may capture decrypted
  data

**Mitigations**:
- `scripts/setup-encrypted-storage.sh` creates the LUKS volume during initial setup
- `scripts/mount-encrypted-storage.sh` unlocks and mounts after reboot
- `scripts/unmount-encrypted-storage.sh` stops the stack and locks the volume
- Both setup and mount scripts `chown` the mount point to `SUDO_USER`, enabling rootless
  Docker to bind-mount the encrypted directories without running Docker as root
- `docker compose` will fail if the encrypted mount directories don't exist — preventing
  accidental unencrypted operation
- When decommissioning a VPS, destroy the LUKS key header or securely wipe the disk
- Consider full-disk encryption (LUKS at OS level) as an additional layer to protect
  `.env`, `dex-config.yaml`, and Docker logs

### T14 — Grist document history retains deleted data

**Risk**: MEDIUM
**Description**: Grist maintains a full action/undo history for every document. When an
admin deletes rows, the data is not truly gone — it remains in the document's action log
and can be recovered through undo or the document history API. While this history is
useful for per-user audit attribution, admins should be aware that deletion is not
permanent.

**Mitigations**:
- Admins must be aware that Grist's "delete" is soft — data persists in history
- To truly purge data, delete and recreate the entire document (which destroys the action
  log)
- Alternatively, use the Grist API to fork the document without history, then delete the
  original
- Document this behavior in operator onboarding materials
- LUKS encryption (T13) ensures that even retained history is encrypted at rest

### T15 — Dex authentication logging

**Risk**: LOW
**Description**: Dex logs authentication events (login attempts, token issuance) to its
container's stdout/stderr. These logs contain admin email addresses and timestamps,
which could reveal who accessed the system and when. Since Dex is publicly accessible,
failed login attempts from attackers will also appear in these logs.

**Mitigations**:
- Docker logging is disabled (`driver: none`) on all containers, including Dex — no log
  data is written to disk
- Consider setting Dex's log level to `error` to suppress routine auth event logging
  (add `logger: { level: error }` to `dex-config.yaml`)
- Do not send Dex logs to any external aggregation service
- This is an inherent limitation — Dex does not support disabling auth event logging

### T16 — Bot processes messages without sender filtering

**Risk**: MEDIUM (partially mitigated by @-mention filtering)
**Description**: The bot processes messages sent to its Signal number or in groups it
belongs to, without sender allowlisting. Any Signal user who knows the bot's phone number
can trigger database queries via direct messages, and any group member can trigger queries
by @-mentioning the bot.

While Grist's SQL endpoint is read-only and the bot only reacts with emoji, unrestricted
access means:
- Any sender can probe the database for information via emoji reactions
- The bot's processing resources are available to all senders (see also T5)
- The bot's phone number effectively becomes a public query interface

**Current status**: Partially mitigated. The bot now implements **@-mention filtering**
for group chats — it only processes group messages where it is explicitly @-mentioned.
This reduces noise and prevents the bot from reacting to unrelated group conversation,
but does not restrict *who* can trigger it within a group.

**Mitigations**:
- **@-mention filtering** (implemented) — in group chats, the bot ignores messages that
  do not @-mention it. Direct messages are still processed without a mention requirement.
- **Per-sender rate limiting** (implemented) — limits each sender to a configurable
  number of messages per time window, preventing message flooding (see T5).
- Consider adding an optional sender allowlist (phone numbers or group IDs) to the bot
  configuration
- Design strategies to avoid leaking sensitive data through emoji reactions — the emoji
  response itself is information disclosure (by design, but should be considered)
- Keep the bot's phone number private — only share with intended users
- For group bots, restrict to specific group IDs rather than responding to all groups

### T17 — Unauthorized access to the Signal chat channel

**Risk**: HIGH
**Description**: An outside actor who gains access to the Signal chat (either by joining
a group the bot monitors, or by messaging the bot's phone number directly) can interact
with the bot as a fully trusted user. The bot has no concept of authorization — any
message that matches a strategy rule triggers a database query and emoji response.

**Attack scenarios**:
- **Group infiltration**: An attacker joins a Signal group the bot monitors. Signal
  groups rely on invite links or admin approval — if a group link is leaked or an
  existing member is compromised, the attacker gains full bot access.
- **Phone number discovery**: If the bot's phone number is leaked (e.g., shared in a
  public channel, visible in a contact list, or guessed from a known number range), any
  Signal user can message the bot directly.
- **Compromised group member**: An attacker who compromises an existing group member's
  phone (SIM swap, malware, physical access) inherits that member's access to the bot.
- **Information extraction via reactions**: The attacker systematically sends messages to
  map out the database contents through the bot's emoji reactions (e.g., iterating
  through names to discover which products exist in a stock check bot).

**Mitigations**:
- **@-mention filtering** (implemented) — the bot only responds to group messages where
  it is explicitly @-mentioned, which adds a minor hurdle for automated enumeration.
  Note: this is defense-in-depth, not a security boundary — any group member who knows
  the bot's name can @-mention it.
- Keep the bot's phone number strictly confidential — treat it as a credential
- For group bots: disable group invite links, require admin approval for new members,
  and regularly audit group membership
- Implement a sender allowlist in the bot configuration (phone numbers or UUIDs) so
  only pre-approved users can trigger queries
- Design strategies to reveal minimal information — prefer binary yes/no reactions over
  reactions that expose specific data values
- **Per-sender rate limiting** (implemented) — slows down enumeration attacks by limiting
  query volume per sender (see T5)
- Monitor for unusual message patterns (high volume from a single sender, systematic
  input sequences) — though this must be done without logging message content
- **Operator-accepted bypass**: the bot auto-trusts senders whose Signal safety
  number has changed (see `src/bot/identity.py`). This restores message delivery
  without operator intervention, but means a SIM-swap or device-takeover attacker
  who re-registers an existing group member's number will be silently re-trusted
  by the bot on their first message. Operators relying on safety-number-change
  as a detection signal should remove the `identity_client` injection in
  `src/bot/main.py`.

### T18 — Admin account compromise and abuse of Grist privileges

**Risk**: HIGH
**Description**: An attacker who compromises an admin account (Dex password) gains full
read/write/delete access to the Grist spreadsheet database. Since Grist and Dex are
publicly accessible via Caddy, no SSH access is required. This goes beyond reading
data — the attacker can:

- **Modify data** to influence bot behavior (e.g., mark all products as in-stock, add
  false entries, change status values that map to specific emoji reactions)
- **Delete data** to cause operational disruption (bot returns "not found" for everything)
- **Export the entire database** through the Grist UI or API
- **Create new documents** to stage data for exfiltration or to cover tracks
- **Alter the API key** to lock out the bot or redirect it to a different document
- **Access document history** to recover previously deleted data (see T14)

Unlike bot access (read-only SQL via the API), admin access is unrestricted.

**Attack vectors**:
- Online brute-force of Dex login (Dex is publicly accessible via Caddy)
- Offline brute-force if `dex-config.yaml` is exfiltrated (mitigated by bcrypt cost factor)
- SSH key compromise (gives VPS access, which gives `.env` and direct container access)
- Session hijacking (if an admin leaves an active Grist browser session unattended)
- Insider threat (a legitimate admin acts maliciously)

**Mitigations**:
- Use strong, randomly generated admin passwords (16+ characters) — enforce via policy
- Use a high bcrypt cost factor (10+ rounds) in `dex-config.yaml`
- Add rate limiting for Dex in the Caddyfile to slow online brute-force attacks
- Close browser sessions when not actively managing data — do not leave sessions open
- Use a dedicated Grist API key with **read-only** scope for the bot — even if an
  attacker compromises the bot, they cannot modify data through the API
- Regularly review `staticPasswords` in `dex-config.yaml` and remove stale accounts
- Consider multiple Grist documents with separate API keys for different data sensitivity
  levels
- For high-security deployments, require multi-person authorization for data changes
  (policy-level, not enforced by Grist)

### T19 — Social engineering attacks targeting admins or group members

**Risk**: HIGH
**Description**: Social engineering is the most likely attack vector for gaining access to
this system. The technical defenses (encryption, firewalls, authentication) are only as
strong as the humans who operate them. An attacker may target:

**Attack scenarios**:

1. **Phishing for SSH keys or Dex passwords**: An attacker impersonates a system
   administrator or colleague and requests SSH private keys, Dex user passwords,
   or the LUKS passphrase via email, Signal, or other channels.

2. **Pretexting for group access**: An attacker poses as a new team member or authorized
   user and asks to be added to the Signal group the bot monitors. Once in the group,
   they have full bot access (see T17).

3. **Signal account takeover (SIM swap)**: An attacker social-engineers the phone carrier
   to transfer the bot's phone number (or a group member's number) to a new SIM. If the
   bot uses a dedicated number registered as a primary device, a SIM swap could allow the
   attacker to re-register the number and hijack the bot's Signal identity.

4. **Credential harvesting through the bot**: An attacker in the group sends messages
   designed to extract information about the system (e.g., probing for error messages
   that reveal table names, column names, or data patterns through emoji responses).

5. **Impersonating the bot**: An attacker creates a new Signal account with a similar
   phone number or display name and messages group members, pretending to be the bot or
   a system notification, to phish for credentials or sensitive information.

6. **Physical access**: An attacker with physical access to the VPS (data center staff,
   co-located hardware) or to an admin's laptop (SSH keys, open tunnels, browser
   sessions) bypasses all network-level controls.

**Mitigations**:
- **Train all admins and group members** on social engineering risks specific to this
  system — especially phishing for SSH keys, Dex passwords, and group invitations
- **Never share credentials over Signal or email** — use an out-of-band channel or a
  password manager's sharing feature
- **Lock Signal registration with a PIN** — enable Signal's Registration Lock on the
  bot's phone number to prevent SIM swap attacks from re-registering the number
- **Use Signal's username feature** instead of sharing the bot's phone number directly
  (reduces phone number exposure)
- **Verify identity before adding group members** — use a trusted out-of-band channel
  to confirm new member requests
- **Restrict group admin privileges** — only designated admins should be able to add
  members or modify group settings
- **Restrict information leaked through errors** — the bot should never return error
  messages that reveal table names, column structures, or SQL syntax
- **Set a display name and avatar** on the bot's Signal account to make impersonation
  harder
- **Log out of Grist sessions** when not in use — do not leave sessions open unattended
- **Enable screen lock** on all devices with SSH keys or open Signal sessions
- **Incident response**: if a social engineering attack is suspected, immediately rotate
  all Dex user passwords, SSH keys, Grist API key, and LUKS passphrase; audit group
  membership and VPS access logs

---

## 4. Security Hardening Checklist

### VPS level
- [ ] SSH key-only authentication enabled
- [ ] Password authentication disabled
- [ ] `fail2ban` installed and active
- [ ] Firewall (UFW) configured — only SSH, 80, and 443 open (T10)
- [ ] Unattended security updates enabled
- [ ] LUKS-encrypted Docker volumes set up via `scripts/setup-encrypted-storage.sh` (T13)
- [ ] Consider full-disk LUKS as additional layer for `.env` and `dex-config.yaml`

### Docker level
- [ ] Rootless Docker installed (recommended — limits container-escape blast radius) (T7)
- [ ] Containers run as non-root
- [ ] `signal-api` port bound to `127.0.0.1` only
- [ ] `grist` port bound to `127.0.0.1` only
- [ ] `dex` port bound to `127.0.0.1` only (Caddy proxies via Docker network)
- [ ] All containers have `logging: driver: none` (no log data written to disk)
- [ ] Resource limits set for all containers
- [ ] Base images pinned and regularly updated (`bbernhard/signal-cli-rest-api`, `gristlabs/grist`, `dexidp/dex`, `caddy`)

### Application level (bot)
- [ ] `.env` file has `chmod 600` permissions
- [ ] `dex-config.yaml` has `chmod 600` permissions
- [ ] `.gitignore` excludes `.env`, `dex-config.yaml`, `hitchhiker.img`, `strategy.yaml`, `strategy.py`, and any key material
- [ ] All Python dependencies pinned to exact versions
- [ ] Grist queries use parameterized `args` only (never string interpolation)
- [ ] `GRIST_TELEMETRY_LEVEL=off` set in docker-compose (not via UI toggle)
- [ ] `GRIST_FORCE_LOGIN=true` set — no anonymous Grist access
- [ ] Input validation on all incoming messages
- [x] Rate limiting implemented per sender (sliding window, configurable via `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW`)
- [ ] Bot logs contain only operational events — no message content, query results, or emoji reactions
- [ ] Error messages do not leak internal details (exception handler suppresses tracebacks)
- [ ] `signalbot`, `httpx`, and `httpcore` loggers set to WARNING level (prevent message/credential leaks)
- [ ] Python strategies reviewed for logging, network access, and secret exfiltration before deployment
- [ ] Admins informed that Grist "delete" does not purge data from document history (T14)

### Signal account & group security
- [ ] Signal Registration Lock (PIN) enabled on the bot's phone number (T19)
- [ ] Bot has a distinctive display name and avatar set (reduces impersonation risk)
- [ ] Bot's phone number treated as confidential — only shared with authorized users (T17)
- [ ] Signal group invite links disabled — admin approval required for new members (T17)
- [ ] Group membership reviewed periodically — remove inactive or unrecognized members
- [ ] Sender allowlist implemented (if applicable) — only pre-approved users trigger queries

### Admin access
- [ ] Dex passwords are 16+ characters, randomly generated for each user (T18)
- [ ] Browser sessions closed when not actively managing data (T18, T19)
- [ ] Rate limiting configured for Dex in Caddyfile (T11, T18)
- [ ] Bot's Grist API key is scoped to read-only on the specific document (T18)
- [ ] Stale user accounts removed from `dex-config.yaml` periodically
- [ ] New Grist users granted access via document sharing (not just Dex login)
- [ ] All admins trained on social engineering risks (phishing, pretexting, SIM swap) (T19)
- [ ] Credentials never shared over Signal or email — use password manager or out-of-band channel
- [ ] Incident response: procedures documented for credential rotation (Dex passwords, SSH keys, API keys, LUKS passphrase)

### Operational
- [ ] Regular backups of `hitchhiker.img` (LUKS volume), `dex-config.yaml`, and `.env`
- [ ] Backups are encrypted at rest
- [ ] Dependency audit scheduled (weekly/monthly)
- [ ] VPS access logs reviewed regularly
- [ ] Incident response plan documented
- [ ] Periodic check: `docker compose logs` contains no message content or query data
- [ ] Dex log level set to `error` to suppress auth event logging (T15)
- [ ] Encrypted volume verified: `scripts/mount-encrypted-storage.sh` runs before `docker compose up`
- [ ] When decommissioning VPS: destroy LUKS key header or securely wipe disk

---

## 5. Data Flow — Security View

### Flow A — Signal bot (read-only queries)

```
Signal User                   VPS
    │                          │
    │  1. E2E encrypted msg    │
    │─────────────────────────►│ signal-api receives & decrypts
    │                          │
    │                          │  2. Plaintext msg on internal Docker network
    │                          │     (never leaves the host)
    │                          │     signal-api ──► bot
    │                          │
    │                          │  3. Bot extracts text, validates input
    │                          │
    │                          │  4. Parameterized SQL query over HTTP (internal Docker network)
    │                          │     bot ──► grist (/api/docs/{docId}/sql)
    │                          │
    │                          │  5. DB result mapped to emoji (in-memory only)
    │                          │
    │                          │  6. Reaction sent back through signal-api
    │  7. E2E encrypted react  │     bot ──► signal-api
    │◄─────────────────────────│
    │                          │
```

### Flow B — Admin access via Caddy (read-write via Grist UI)

```
Admin Browser                 VPS
    │                          │
    │  1. HTTPS request        │
    │     yourdomain.com ──────│──► Caddy ──► grist:8484
    │                          │
    │  2. OIDC redirect        │
    │     ──► dex.yourdomain.com  Caddy ──► dex:5556 (login form)
    │                          │
    │  3. Admin enters Dex     │
    │     credentials          │  bcrypt password verification
    │                          │
    │  4. OIDC callback        │
    │     dex ──► grist        │  id_token with email claim
    │                          │
    │  5. Grist session        │
    │     (cookie)             │  Full spreadsheet UI access
    │                          │
```

**Key security properties of Flow A (bot)**:
- Message content is E2E encrypted between Signal user and VPS — Signal servers cannot read it
- Plaintext only exists inside the Docker network, between `signal-api`, `bot`, and `grist` containers
- Grist queries must use parameterized `args` to prevent SQL injection
- The emoji reaction reveals only a single emoji to the Signal user — but note that the
  emoji itself could leak information about the database result (by design)
- No message content is persisted by the bot — however, `signal-cli` does persist PII
  (phone numbers, contacts, group membership) in the `signal-data` volume (see T1)
- The bot has no authentication layer — any Signal user who can message the bot's number
  (or join a monitored group) has full query access (see T17)

**Key security properties of Flow B (admin)**:
- Admin access via Caddy requires only a Dex password (single-factor). For SSH tunnel
  access, it is two-factor (SSH key + Dex password). Since Dex is publicly accessible,
  strong passwords and rate limiting on the Dex endpoint are critical.
- Each user has a distinct Dex account — changes are attributed per-user in Grist's
  document history
- Grist's per-user access control allows document owners to set Viewer/Editor/Owner roles
- Caddy exposes Grist and Dex on ports 80/443 — all other services remain localhost-only

**Shared security properties**:
- Grist retains a full action history (undo log) — deleted data is not truly purged (see T14).
  This history serves as a per-user audit trail showing who changed what and when.
- Both Docker volumes (`signal-data`, `grist-data`) are backed by LUKS-encrypted storage —
  data is encrypted at rest and inaccessible without the passphrase (see T13)
