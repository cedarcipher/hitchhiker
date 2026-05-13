# Hitchhiker

A privacy-first framework for building Signal bots backed by a self-hosted
[Grist](https://www.getgrist.com/) spreadsheet database.

You provide a **strategy** — a YAML file or Python module that defines what to query
and how to react — and Hitchhiker handles everything else: Signal connectivity, Grist
integration, Docker deployment, admin authentication, and privacy-by-default logging.

```
signal user  ──►  signal-api  ──►  bot  ──►  strategy.yaml  ──►  grist  ──►  reaction
```

### Example use cases

**Product stock check** — a group member asks if a product is in stock, the bot reacts
with a checkmark or stop sign:

```yaml
# strategy.yaml
tables:
  Products:
    columns:
      name: text
      in_stock: integer

rules:
  - name: stock_check
    match:
      prefix: "stock "             # "stock Bandages" → {input} = "Bandages"
    query:
      table: Products
      select: [in_stock]
      where:
        name: "{input}"
    react:
      map:
        column: in_stock
        values:
          1: "✅"
          0: "🚫"
      empty: "❓"                   # product not found
```

**Expertise lookup** — someone asks if a person in the chat can help with a topic, the
bot reacts with thumbs up or down. This needs two variables (person + topic), so it
uses a Python strategy:

```python
# strategy.py
import re

class Strategy:
    PATTERN = re.compile(r"^can (\w+) help with (\w+)", re.IGNORECASE)

    def query(self, message_text: str) -> tuple[str, list]:
        m = self.PATTERN.search(message_text.strip())
        if not m:
            return ("", [])
        person, topic = m.group(1), m.group(2)
        return (
            "SELECT person FROM Experts WHERE person = ? AND topic = ?",
            [person, topic],
        )

    def react(self, message_text: str, rows: list[dict]) -> str | None:
        if rows:
            return "👍"
        return "👎"
```

## Architecture

Four Docker containers on the same network (plus optional Caddy for TLS):

| Service      | Image                                  | Purpose                              |
|--------------|----------------------------------------|--------------------------------------|
| `signal-api` | `bbernhard/signal-cli-rest-api:latest` | Bridge between the bot and Signal    |
| `bot`        | Built from `Dockerfile`                | Python bot — queries Grist, reacts   |
| `grist`      | `gristlabs/grist:latest`              | Spreadsheet DB with REST/SQL API     |
| `dex`        | `dexidp/dex:latest`                   | OIDC identity provider (multi-user login) |
| `caddy`      | `caddy:2` *(optional)*                | TLS reverse proxy for public Grist access |

All services are bound to `127.0.0.1` and accessible only via SSH tunnel. If you need
public HTTPS access to Grist (without SSH), enable the optional Caddy service — see
"Public access via Caddy" below. Caddy must also proxy Dex so the browser can complete
the OIDC login flow.

## Prerequisites

- Docker Engine 24+ with Docker Compose v2 (rootful or rootless)
- `cryptsetup` (for LUKS encrypted storage — see "Encrypted Storage" below)
- A phone number for the bot (see "Register the Signal account" below)
- For VPS deployment: SSH access to the server

Hitchhiker runs the same way on a local machine or a remote VPS. The only difference
is how you access the web UIs: locally you open `localhost` directly, on a VPS you use
SSH tunnels.

## Quick Start

For those who want the shortest path to a running bot:

```bash
# 1. Clone
git clone <repo-url> ~/hitchhiker && cd ~/hitchhiker

# 2. Set up encrypted storage (required — stores Signal keys and Grist data)
sudo apt install cryptsetup    # Debian/Ubuntu
sudo ./scripts/setup-encrypted-storage.sh
# You will be prompted to set a passphrase — store it securely.

# 3. Generate secrets
GRIST_OIDC_IDP_CLIENT_SECRET=$(openssl rand -hex 32)
GRIST_SESSION_SECRET=$(openssl rand -hex 32)
ALICE_HASH=$(htpasswd -nbBC 10 "" 'alice-password-here' | cut -d: -f2)
BOB_HASH=$(htpasswd -nbBC 10 "" 'bob-password-here' | cut -d: -f2)

# 4. Create .env
cp .env.example .env
# Edit .env → set SIGNAL_PHONE_NUMBER, paste GRIST_OIDC_IDP_CLIENT_SECRET and GRIST_SESSION_SECRET

# 5. Create dex-config.yaml (multi-user login for Grist)
cat > dex-config.yaml <<YAML
issuer: https://dex.yourdomain.com/dex
storage:
  type: memory
web:
  http: 0.0.0.0:5556
staticClients:
  - id: grist
    secret: ${GRIST_OIDC_IDP_CLIENT_SECRET}
    name: Grist
    redirectURIs:
      - https://yourdomain.com/oauth2/callback
enablePasswordDB: true

staticPasswords:
  - email: alice@localhost
    hash: "${ALICE_HASH}"
    username: Alice
  - email: bob@localhost
    hash: "${BOB_HASH}"
    username: Bob
YAML

# 6. Write a strategy
cat > strategy.yaml <<YAML
rules:
  - name: stock_check
    match:
      prefix: "stock "
    query:
      table: Products
      select: [in_stock]
      where:
        name: "{input}"
    react:
      map:
        column: in_stock
        values:
          1: "✅"
          0: "🚫"
      empty: "❓"
YAML

# 7. Build and start
docker compose up -d --build

# 8. Link your Signal account (scan QR code)
#    Local: open http://localhost:8090/v1/qrcodelink?device_name=bot
#    VPS:   ssh -L 8090:127.0.0.1:8090 user@vps, then open the same URL

# 9. Set up Grist (create tables, get API key)
#    Local: open http://localhost:8484
#    VPS:   ssh -L 8484:127.0.0.1:8484 user@vps, then open the same URL
#    → Log in with alice@localhost / alice-password-here (or bob@localhost)
#    → Create a document, note the doc ID from the URL
#    → Create a "Products" table with columns: name (text), in_stock (integer)
#    → Go to profile → generate API key
#    → Add GRIST_API_KEY and GRIST_DOC_ID to .env

# 10. Restart with the Grist credentials
docker compose restart bot
```

The bot is now running. Send `stock Bandages` to the bot's Signal number — it will
react with a checkmark, stop sign, or question mark depending on the data in Grist.

## Detailed Setup

### 1. Clone and configure

```bash
git clone <repo-url> ~/hitchhiker && cd ~/hitchhiker
cp .env.example .env
```

Edit `.env` with your values:

```bash
# Signal
SIGNAL_PHONE_NUMBER=+1234567890

# Grist (fill these in after step 7 below)
GRIST_API_KEY=
GRIST_DOC_ID=

# OIDC (Grist ↔ Dex) — generate with: openssl rand -hex 32
GRIST_OIDC_IDP_CLIENT_SECRET=<random string — must match dex-config.yaml>
GRIST_SESSION_SECRET=<random string>
```

> **Note**: `GRIST_API_KEY` and `GRIST_DOC_ID` are blank at first. You'll fill them in
> after Grist is running (step 7). The bot will fail to start until they're set — that's
> expected.

### 2. Configure Dex (OIDC authentication)

Grist's open-source edition has no built-in password login. It delegates authentication
to an external OIDC provider. [Dex](https://dexidp.io/) fills this role as a lightweight
identity provider that runs alongside Grist on the same Docker network.

**How the login flow works:**

```
browser                      grist                   caddy               dex (5556)
   │                             │                      │                     │
   │  GET yourdomain.com         │                      │                     │
   │────────────────────────────────────────────────────►│                     │
   │                             │                      │──►grist:8484        │
   │                             │                      │                     │
   │  302 → dex.yourdomain.com/dex/auth                 │                     │
   │◄───────────────────────────────────────────────────│                     │
   │                             │                      │                     │
   │  GET dex.yourdomain.com/dex/auth (login form)      │                     │
   │────────────────────────────────────────────────────►│──►dex:5556         │
   │                             │                      │                     │
   │  POST email + password      │                      │                     │
   │────────────────────────────────────────────────────►│──►dex:5556         │
   │                             │                      │                     │
   │  302 → yourdomain.com/oauth2/callback?code=...     │                     │
   │◄───────────────────────────────────────────────────│                     │
   │                             │                      │                     │
   │  GET /oauth2/callback       │                      │                     │
   │────────────────────────────────────────────────────►│──►grist:8484       │
   │                             │  exchange code for token                   │
   │                             │──────────────────────────────────────────►│
   │                             │  ◄── id_token (email)                     │
   │                             │                      │                     │
   │  200 OK (session cookie)    │                      │                     │
   │◄───────────────────────────────────────────────────│                     │
```

Three values link Grist and Dex together — they must match across `.env`,
`docker-compose.yml`, and `dex-config.yaml`:

| Value                | Set in `.env` as                    | Used in `dex-config.yaml` as                |
|----------------------|-------------------------------------|---------------------------------------------|
| Client ID            | hardcoded `grist` in compose        | `staticClients[0].id`                       |
| Client secret        | `GRIST_OIDC_IDP_CLIENT_SECRET`      | `staticClients[0].secret`                   |
| Callback URL         | derived from `GRIST_OIDC_SP_HOST`   | `staticClients[0].redirectURIs[0]`          |

#### Generate secrets

```bash
# OIDC client secret (shared between Grist and Dex)
openssl rand -hex 32

# Grist session signing key
openssl rand -hex 32
```

#### Create `dex-config.yaml`

This file is gitignored — it contains hashed credentials and the OIDC client secret.

```yaml
issuer: https://dex.yourdomain.com/dex

storage:
  type: memory          # no persistent DB needed — passwords are in this file

web:
  http: 0.0.0.0:5556    # listen inside the container; Caddy proxies to this

staticClients:
  - id: grist
    secret: <paste GRIST_OIDC_IDP_CLIENT_SECRET from .env>
    name: Grist
    redirectURIs:
      - https://yourdomain.com/oauth2/callback

enablePasswordDB: true

# Each user needs a unique email (used at login) and a bcrypt hash of their password.
# The username is a display name shown in Grist (cosmetic only).
staticPasswords:
  - email: alice@example.com
    hash: <bcrypt hash>             # see "Generate a bcrypt password hash" below
    username: Alice
  - email: bob@example.com
    hash: <bcrypt hash>
    username: Bob
  - email: carol@example.com
    hash: <bcrypt hash>
    username: Carol
```

#### Generate a bcrypt password hash

```bash
htpasswd -nbBC 10 "" 'your-password-here' | cut -d: -f2
```

Use cost factor 10 or higher. Paste the output (starting with `$2y$`) as the `hash`
value in `dex-config.yaml`.

#### Adding or removing users

To add a user, generate a bcrypt hash for their password and add an entry to the
`staticPasswords` list in `dex-config.yaml`:

```yaml
staticPasswords:
  # ... existing users ...
  - email: dave@example.com       # must be unique — this is what they type at login
    hash: <bcrypt hash>            # htpasswd -nbBC 10 "" 'their-password' | cut -d: -f2
    username: Dave                 # display name shown in Grist
```

To remove a user, delete their entry from the list. Then restart Dex:

```bash
docker compose restart dex
```

No database migration or external service involved. Dex reads the file on startup.

After adding a new user, the **document owner** (the first user who created the Grist
document) must share the document with them: open the document in Grist, click the
**Share** button (top-right), and add the new user's email address. Without this step,
the new user can log in but won't see any documents.

### 3. Set up encrypted storage

Signal key material and Grist database files are stored in Docker volumes backed by a
LUKS-encrypted loopback file. This is a **hard requirement** — `docker compose` will
refuse to start if the encrypted volume is not mounted (see
[THREAT_MODEL.md](THREAT_MODEL.md) T13).

```bash
# Install cryptsetup if not already present
sudo apt install cryptsetup    # Debian/Ubuntu
sudo dnf install cryptsetup    # Fedora/RHEL

# Create the encrypted volume (default: 512 MB at /mnt/hitchhiker)
sudo ./scripts/setup-encrypted-storage.sh
```

You will be prompted to set a LUKS passphrase. **Store this passphrase securely** —
losing it means losing all Signal session data and Grist documents.

The script creates:
- `/mnt/hitchhiker/signal/` — backing store for the `signal-data` Docker volume
- `/mnt/hitchhiker/grist/` — backing store for the `grist-data` Docker volume

To customize the size or mount point:

```bash
sudo ./scripts/setup-encrypted-storage.sh 1024 ./hitchhiker.img /mnt/hitchhiker
#                                          ^^^^ size in MB
```

> **After every reboot**, unlock and mount the volume before starting Docker:
>
> ```bash
> sudo ./scripts/mount-encrypted-storage.sh
> docker compose up -d
> ```

### 4. Write your strategy

Create a `strategy.yaml` in the project root (see "Writing a Strategy" below for the
full reference). A minimal example:

```yaml
rules:
  - name: lookup
    match:
      prefix: "check "
    query:
      table: MyTable
      select: [status]
      where:
        name: "{input}"
    react:
      map:
        column: status
        values:
          active: "✅"
          inactive: "🚫"
      empty: "❓"
```

### 5. Build and start the stack

```bash
docker compose up -d --build
```

The `--build` flag builds the bot container from the `Dockerfile`. On subsequent runs
after code changes, re-run with `--build` to pick up changes. For strategy-only changes,
`docker compose restart bot` is sufficient since the strategy file is mounted as a
volume.

The first startup will pull images for `signal-api`, `grist`, and `dex` (~1 GB total).
The bot will restart in a loop until the Signal account is registered and Grist
credentials are configured — that's normal.

### 6. Register the Signal account (first time only)

The bot needs a Signal identity to send and receive messages. This is handled by the
`signal-api` container ([signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)),
which wraps the [signal-cli](https://github.com/AsamK/signal-cli) client.

**Yes, a real phone number is required.** Signal ties every account to a phone number.
There are two ways to set this up:

#### Option A — Link to an existing Signal account (quick start)

The bot joins your existing Signal number as a **secondary device**, just like Signal
Desktop. Your phone stays active and the bot shares the same number.

```
your phone (primary)  ──►  Signal servers  ◄──  signal-api (linked device)
```

**Steps:**

1. Access the signal-api:

   ```bash
   # Local: ports are already bound to localhost
   # VPS: open an SSH tunnel first
   ssh -L 8090:127.0.0.1:8090 user@vps
   ```

2. Open `http://localhost:8090/v1/qrcodelink?device_name=bot` in your browser. A QR
   code will appear (it expires in ~30 seconds — refresh if needed).

3. On your phone, open Signal > **Settings > Linked Devices > +** and scan the QR code.

4. Once linked, the signal-api container stores session keys in `./signal-cli-config/`.
   The bot can now send and receive messages on your number.

**Trade-offs:**
- Quick — no new phone number needed
- Your phone must stay active (Signal may unlink inactive secondary devices)
- Max 3 linked devices per account (phone + desktop + bot = 3)
- The bot sends/receives as *you*, not a separate identity

#### Option B — Register a dedicated number (recommended for production)

Register a **separate phone number** exclusively for the bot. The bot becomes the
primary (and only) device for that number.

```
dedicated number  ──►  signal-api (primary device)  ──►  Signal servers
```

You need a number that can receive a single SMS for verification. Options:
- A cheap prepaid SIM
- A VoIP number (Google Voice, TextNow, etc.) — must be able to receive SMS
- A landline (use voice verification instead of SMS)

**Steps:**

1. Access the signal-api (same as Option A):

   ```bash
   # Local: ports are already bound to localhost
   # VPS: open an SSH tunnel first
   ssh -L 8090:127.0.0.1:8090 user@vps
   ```

2. Solve the captcha at https://signalcaptchas.org/registration/generate.html.
   After solving, right-click the "Open Signal" link and **copy the link address**.
   It starts with `signalcaptcha://`.

3. Register the number (replace `+1234567890` and the captcha value):

   ```bash
   curl -X POST -H "Content-Type: application/json" \
     -d '{"captcha": "signalcaptcha://signal-hcaptcha.XXXX...", "use_voice": false}' \
     "http://localhost:8090/v1/register/+1234567890"
   ```

   For a landline (voice call instead of SMS), set `"use_voice": true`.

4. Check the phone for an SMS verification code, then verify:

   ```bash
   curl -X POST \
     "http://localhost:8090/v1/register/+1234567890/verify/123-456"
   ```

5. Done. The bot now owns this number. Set `SIGNAL_PHONE_NUMBER=+1234567890` in `.env`.

**Trade-offs:**
- Fully independent — no dependency on a personal phone
- Separate identity for the bot (users message the bot's number, not yours)
- Requires obtaining a phone number
- That number can't also be used on the Signal mobile app

#### After registration (either option)

The session keys are stored in `./signal-cli-config/`. This directory is critical —
losing it means re-registering or re-linking. Back it up and never commit it to git.

Verify the bot can reach Signal:

```bash
# Check the signal-api is healthy
curl http://localhost:8090/v1/health

# List registered accounts
curl http://localhost:8090/v1/accounts
```

### 7. Set up Grist (first time only)

Access the Grist UI:

```bash
# Local: open http://localhost:8484 directly
# VPS with Caddy: open https://yourdomain.com directly
# VPS without Caddy: open an SSH tunnel first
ssh -L 8484:127.0.0.1:8484 -L 5556:127.0.0.1:5556 user@vps
```

Open Grist in your browser. Dex will prompt for email and password
(the credentials from `dex-config.yaml`). Once logged in:

1. Create a document and note its ID from the URL (e.g. `http://localhost:8484/o/docs/sK7x...` → the ID is `sK7x...`)
2. Create a table with the columns your strategy expects
3. Add some test data so the bot has something to query
4. Go to your profile (top-right menu) to generate an API key
5. Add `GRIST_API_KEY` and `GRIST_DOC_ID` to `.env`
6. Restart the bot: `docker compose restart bot`

### 8. Verify everything works

```bash
# Check all containers are running
docker compose ps

# Check bot logs for startup confirmation
docker compose logs bot --tail 20

# Send a direct message to the bot's Signal number and check for a reaction
# In a group chat, @-mention the bot: "@Bot stock Bandages"
```

### 9. Using the bot in a group chat

The bot supports Signal group chats with **@-mention filtering** — in groups, it only
responds to messages where it is explicitly @-mentioned. Direct messages do not require
a mention.

#### Adding the bot to a group

- **Linked device (Option A):** If the bot is linked to your personal number, it
  automatically joins all groups your number belongs to. No extra step needed.
- **Dedicated number (Option B):** Add the bot's phone number to the group via
  Signal's "Add members" feature. A group admin must approve the addition.

#### Interacting with the bot in a group

In a group chat, **@-mention the bot** before your query:

```
@Bot stock Bandages      →  bot reacts ✅
@Bot stock Unobtanium    →  bot reacts 🚫
@Bot stock Widgets       →  bot reacts ❓  (not in database)
```

Messages without an @-mention are silently ignored — the bot won't react to unrelated
group conversation. In direct messages, no @-mention is needed.

#### Group security recommendations

- **Disable group invite links** — require admin approval for new members
- **Restrict who can edit group info** — set to "Only admins" in group settings
- **Regularly audit group membership** — remove inactive or unrecognized members
- **Keep the bot's phone number private** — only share with intended group admins

### 10. Rate limiting

The bot enforces **per-sender rate limiting** to protect against message flooding and
database enumeration. Each sender (identified by their Signal UUID) is allowed a maximum
number of messages within a rolling time window. Excess messages are silently ignored.

Configure via environment variables in `.env`:

```bash
# Maximum messages per sender within the window (default: 10)
RATE_LIMIT_MAX=10

# Rolling window size in seconds (default: 60)
RATE_LIMIT_WINDOW=60
```

**How it works:**

- The rate limiter uses a **sliding window** per sender UUID — not a fixed clock window,
  so bursts near a boundary don't get double the allowance.
- Rate limiting runs **after** @-mention filtering — unmentioned group messages don't
  consume a sender's allowance.
- Rate-limited messages are **silently dropped** — no error reply, no emoji reaction.
  This is intentional: replying to a rate-limited user would itself generate traffic.
- The limiter is **in-memory only** — no sender data is persisted or logged. UUIDs are
  used instead of phone numbers for privacy.

**Tuning guidelines:**

| Scenario              | Suggested `MAX` | Suggested `WINDOW` |
|-----------------------|-----------------|---------------------|
| Small trusted group   | 20              | 60                  |
| Public-facing bot     | 5               | 60                  |
| Stock check bot       | 10              | 60                  |

The defaults (10 messages / 60 seconds) are reasonable for most deployments. Signal's
own server-side rate limits are unlikely to be hit since the bot only sends lightweight
emoji reactions (not full text messages), but the bot-side rate limiter protects Grist
from being hammered by a single user.

### Local vs. VPS deployment

| Step                          | Local                                     | VPS                                           |
|-------------------------------|-------------------------------------------|-----------------------------------------------|
| Signal-api UI (QR code)      | `http://localhost:8090/...`               | SSH tunnel: `ssh -L 8090:127.0.0.1:8090 user@vps`, then same URL |
| Grist admin UI                | `http://localhost:8484`                   | With Caddy: `https://yourdomain.com`; without: SSH tunnel `ssh -L 8484:127.0.0.1:8484 -L 5556:127.0.0.1:5556 user@vps` |
| Strategy edits                | Edit file, `docker compose restart bot`   | Same (edit on server or scp)                  |
| Persistence                   | Data in `./signal-cli-config/` and Docker volume | Same — back up these paths                   |
| Security                      | Only you can access localhost              | SSH tunnel for signal-api; Caddy for public Grist + Dex access |

## Writing a Strategy

A strategy defines what to query from Grist and how to react. Hitchhiker supports two
formats:

- **YAML** (declarative) — define rules as data, no code required
- **Python** (imperative) — full programmatic control for complex logic

### YAML strategy (recommended for most use cases)

A YAML strategy is a list of **rules**. Rules are evaluated top-to-bottom — the first
rule whose `match` pattern matches the incoming message is applied.

```yaml
# strategy.yaml
rules:
  - name: order_lookup
    match:
      prefix: "order "           # matches "order 12345" → {input} = "12345"
    query:
      table: Orders
      select: [status]
      where:
        order_id: "{input}"
    react:
      map:
        column: status
        values:
          shipped: "📦"
          delivered: "✅"
          cancelled: "❌"
        default: "⏳"
      empty: "❓"
```

#### Match types

| Type       | Example                  | Behavior                                      |
|------------|--------------------------|-----------------------------------------------|
| `prefix`   | `prefix: "order "`       | Starts with string; remainder → `{input}`     |
| `suffix`   | `suffix: " please"`      | Ends with string; text before → `{input}`     |
| `exact`    | `exact: "ping"`          | Exact match (case-insensitive)                |
| `contains` | `contains: "help"`       | Contains substring                            |
| `regex`    | `regex: "^(\\d{4,})$"`   | Regex; first capture group → `{input}`        |
| `any_of`   | `any_of: [...]`          | List of matchers; rule fires if any match (first capture wins) |
| `all_of`   | `all_of: [...]`          | List of matchers; rule fires only if all match (last capture wins) |
| `any`      | `any: true`              | Matches every message (catch-all)             |

#### Template variables

Use these in `query.where` values, `query.args`, and `query.sql`:

| Variable    | Value                                         |
|-------------|-----------------------------------------------|
| `{message}` | Full message text, stripped and lowercased     |
| `{input}`   | Text extracted by the match pattern            |
| `{raw}`     | Original unprocessed message text              |

#### Query formats

```yaml
# Structured query (recommended) — compiles to parameterized SQL
query:
  table: Orders
  select: [status]
  where:
    order_id: "{input}"

# Raw SQL — for joins, aggregates, or complex conditions
query:
  sql: "SELECT status FROM Orders WHERE order_id = ? AND active = 1"
  args: ["{input}"]
```

#### React formats

```yaml
# Map column values to emoji
react:
  map:
    column: status
    values:
      shipped: "📦"
      delivered: "✅"
    default: "⏳"
  empty: "❓"            # when query returns no rows

# Use a column's value directly as the emoji
react:
  column: emoji

# Static emoji (no query needed)
react:
  emoji: "🏓"
```

#### Optional: table schema declaration

Declare expected tables for documentation and startup validation:

```yaml
tables:
  Orders:
    columns:
      order_id: text
      status: text

rules:
  # ...
```

### YAML example: keyword allowlist

```yaml
# strategy.yaml
rules:
  - name: keyword_check
    match:
      any: true
    query:
      table: Allowlist
      select: [emoji]
      where:
        word: "{message}"
    react:
      column: emoji
```

### YAML example: optional keyword via `any_of`

Trigger on a keyword *or* a bare pattern. Useful when users sometimes send
`stock BAND-12345` and sometimes just `BAND-12345`:

```yaml
rules:
  - name: stock_check
    match:
      any_of:
        - prefix: "stock "
        - regex: "^BAND-\\d+$"
    query:
      table: Products
      select: [in_stock]
      where:
        sku: "{input}"
    react:
      map:
        column: in_stock
        values:
          1: "✅"
          0: "🚫"
      empty: "❓"
```

### YAML example: multi-rule strategy

```yaml
# strategy.yaml — first matching rule wins
rules:
  - name: greeting
    match:
      exact: "ping"
    react:
      emoji: "🏓"

  - name: order_lookup
    match:
      prefix: "order "
    query:
      table: Orders
      select: [status]
      where:
        order_id: "{input}"
    react:
      map:
        column: status
        values:
          shipped: "📦"
          delivered: "✅"
        default: "⏳"
      empty: "❓"

  - name: fallback
    match:
      any: true
    query:
      table: Allowlist
      select: [emoji]
      where:
        word: "{message}"
    react:
      column: emoji
```

### Python strategy

For complex logic that YAML can't express, write a Python class with `query()` and
`react()` methods:

```python
# strategy.py
class Strategy:
    def query(self, message_text: str) -> tuple[str, list]:
        text = message_text.strip()
        if not text.startswith("order "):
            return ("", [])  # no query for this message
        order_id = text.removeprefix("order ")
        return ("SELECT status FROM Orders WHERE order_id = ?", [order_id])

    def react(self, message_text: str, rows: list[dict]) -> str | None:
        if not rows:
            return "❓"
        return {
            "shipped": "📦",
            "delivered": "✅",
            "cancelled": "❌",
        }.get(rows[0]["status"], "⏳")
```

Use Python when you need multi-step logic, external API calls, complex text parsing,
or anything beyond simple pattern matching and value lookups.

### Deploying your strategy

Place your strategy file (`strategy.yaml` or `strategy.py`) in the project root.
Docker Compose mounts it read-only into the bot container:

```yaml
# docker-compose.yml (already configured for YAML)
bot:
  volumes:
    - ./strategy.yaml:/app/strategy.yaml:ro
  environment:
    - STRATEGY_PATH=/app/strategy.yaml
```

To use a Python strategy instead, change the volume mount and `STRATEGY_PATH` to point
to `strategy.py`.

To update the strategy, edit the file and restart the bot:

```bash
docker compose restart bot
```

### Testing a strategy locally

YAML strategies can be tested with the built-in `YamlStrategy` class:

```python
from bot.yaml_strategy import YamlStrategy

s = YamlStrategy.from_file("strategy.yaml")
sql, args = s.query("order 12345")
assert args == ["12345"]

emoji = s.react("order 12345", [{"status": "shipped"}])
assert emoji == "📦"
```

Python strategies are plain classes — test them directly:

```python
from strategy import Strategy

s = Strategy()
sql, args = s.query("order 12345")
assert sql == "SELECT status FROM Orders WHERE order_id = ?"

emoji = s.react("order 12345", [{"status": "shipped"}])
assert emoji == "📦"
```

## Admin Data Management

All data management happens directly in the Grist spreadsheet UI. Each user logs
in with their own Dex credentials, and Grist tracks who made each change via its
built-in document history.

### Accessing Grist

```bash
# Local: open http://localhost:8484 directly
# VPS with Caddy: open https://yourdomain.com directly
# VPS without Caddy: open an SSH tunnel (must also tunnel Dex for login)
ssh -L 8484:127.0.0.1:8484 -L 5556:127.0.0.1:5556 user@vps

# Log in with your Dex credentials from dex-config.yaml
```

For public HTTPS access without SSH tunnels, see "Public access via Caddy" below.

### Manual entry

Edit cells directly in the Grist spreadsheet UI. Changes are immediate and
visible to the bot on its next query.

### Bulk CSV import

In the Grist UI: **Add New > Import from file** — select a CSV, map columns,
and choose to create a new table or merge into an existing one.

### Sharing documents with users

The first user to create a Grist document is its **owner**. Other users must be
explicitly granted access before they can see or edit it:

1. Open the document in Grist
2. Click **Share** (top-right)
3. Add the user's email address (the `email` field from `dex-config.yaml`)
4. Choose their role: **Viewer**, **Editor**, or **Owner**

Users who are not shared on a document can log in to Grist but will see an empty
home screen.

### Viewing change history

Grist's built-in **Document History** tracks every change and attributes it to
the user who made it. This serves as the audit trail for knowing who did what:

1. Open a document in Grist
2. Click the clock icon in the bottom-left panel (or **Document History** in the
   left sidebar)
3. Switch to the **Activity** tab to see a chronological list of changes with
   the user and timestamp for each

### Public access via Caddy

For deployments where SSH tunnels are inconvenient (e.g. multiple non-technical
users), you can optionally expose Grist and Dex publicly via Caddy with automatic TLS.
Dex **must** be publicly accessible — the browser redirects to Dex during login, so it
needs to be reachable from the user's machine, not just inside the Docker network.

1. Copy the example config: `cp Caddyfile.example Caddyfile`
2. Edit `Caddyfile` — replace `yourdomain.com` and `dex.yourdomain.com` with your actual domains
3. Update `GRIST_OIDC_SP_HOST` in `docker-compose.yml` to `https://yourdomain.com`
4. Update `GRIST_OIDC_IDP_ISSUER` in `docker-compose.yml` to `https://dex.yourdomain.com/dex`
5. Update `issuer` in `dex-config.yaml` to `https://dex.yourdomain.com/dex`
6. Update `redirectURIs` in `dex-config.yaml` to `https://yourdomain.com/oauth2/callback`
7. Start Caddy: `docker compose --profile caddy up -d`

Caddy provisions TLS certificates automatically via Let's Encrypt. Both domains'
DNS must point to the server, and ports 80/443 must be open in your firewall.

## Configuration Reference

| Variable                       | Required | Default              | Description                          |
|--------------------------------|----------|----------------------|--------------------------------------|
| `SIGNAL_PHONE_NUMBER`          | Yes      | —                    | Bot's Signal phone number            |
| `GRIST_API_KEY`                | Yes      | —                    | Grist API key (read-only scope)      |
| `GRIST_DOC_ID`                 | Yes      | —                    | Grist document ID                    |
| `GRIST_OIDC_IDP_CLIENT_SECRET` | Yes      | —                    | OIDC shared secret (Grist ↔ Dex)    |
| `GRIST_SESSION_SECRET`         | Yes      | —                    | Grist session signing key            |
| `STRATEGY_PATH`                | No       | `/app/strategy.yaml` | Path to strategy file (`.yaml` or `.py`) |
| `SIGNAL_SERVICE_URL`           | No       | `signal-api:8080`    | Overridden in docker-compose.yml     |
| `GRIST_API_URL`                | No       | `http://grist:8484`  | Overridden in docker-compose.yml     |

## Privacy

This is a privacy-first service.

- **Encrypted at rest** — Signal keys and Grist data are stored in LUKS-encrypted Docker volumes
- **Per-user change tracking** — Grist's built-in document history attributes each change to the logged-in user (see "Viewing change history" above). Enterprise-only audit log *streaming* is not available in grist-core, but the built-in action history provides full per-user attribution locally
- **No telemetry** — `GRIST_TELEMETRY_LEVEL=off` prevents data from leaving the VPS
- **No message logging** — the bot never logs message content, query results, or reactions
- **No Docker logging** — all containers use `logging: driver: none`
- **No external log aggregation** — logs stay on the VPS and auto-rotate

## Updating

```bash
cd ~/hitchhiker
git pull
docker compose build bot
docker compose up -d
```

## Encrypted Storage

All sensitive data (Signal keys and Grist documents) is stored in Docker volumes backed
by a LUKS-encrypted loopback file. This is a **hard requirement** — the stack will not
start without it.

| What                        | Docker Volume   | Encrypted Backing Store                  |
|-----------------------------|-----------------|------------------------------------------|
| Signal keys, PII, sessions  | `signal-data`   | `/mnt/hitchhiker/signal/` (LUKS)         |
| Grist documents (SQLite)    | `grist-data`    | `/mnt/hitchhiker/grist/` (LUKS)          |

The encrypted volume image (`hitchhiker.img`) is created by
`scripts/setup-encrypted-storage.sh` and must be unlocked after every reboot:

```bash
# After reboot — unlock and mount
sudo ./scripts/mount-encrypted-storage.sh
docker compose up -d

# Graceful shutdown — stop containers, lock volume
sudo ./scripts/unmount-encrypted-storage.sh
```

The mount point defaults to `/mnt/hitchhiker`. Override it by setting
`HITCHHIKER_ENCRYPTED_MOUNT` in `.env`.

### Rootless Docker

The encrypted storage scripts work with both rootful and rootless Docker. LUKS
setup still requires `sudo` (dm-crypt is a kernel feature), but the scripts
automatically `chown` the mount point to the user who ran `sudo`, so rootless
Docker can bind-mount the directories without additional configuration.

```bash
# Works the same — sudo is only needed for LUKS, not for Docker
sudo ./scripts/setup-encrypted-storage.sh
docker compose up -d    # no sudo needed with rootless Docker
```

## Local Development (without LUKS)

LUKS encryption is required in production but adds friction locally (`sudo`,
`cryptsetup`, passphrase on every reboot). To skip it during development, copy
the example override file:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up -d --build
```

Docker Compose automatically merges `docker-compose.override.yml` on top of
`docker-compose.yml`. The override replaces the LUKS-encrypted bind mounts with
plain Docker named volumes — no `cryptsetup`, no `sudo`, no passphrase.

To verify the override is active:

```bash
docker compose config | grep -A2 'signal-data'
# Should show a simple named volume, not a bind mount with device: /mnt/hitchhiker/...
```

To go back to encrypted storage, delete the override file:

```bash
rm docker-compose.override.yml
```

> **Warning**: The override file is gitignored and must never be used in
> production. Signal keys and Grist data will be stored unencrypted on your
> local Docker volume.

## Persistent Data

| Path / Volume                 | Contents                         | Encrypted? | Back up? |
|-------------------------------|----------------------------------|:----------:|----------|
| `signal-data` (Docker volume) | Signal keys and session data     | Yes (LUKS) | Yes      |
| `grist-data` (Docker volume)  | Grist documents (SQLite)         | Yes (LUKS) | Yes      |
| `caddy-data` (Docker volume)  | TLS certificates (Let's Encrypt) | No         | Optional |
| `hitchhiker.img`              | LUKS container (holds the above) | Self       | Yes      |
| `./strategy.yaml`             | Your decision logic (or `.py`)   | No         | Yes      |
| `./dex-config.yaml`           | User password hashes + OIDC secret | No       | Yes      |
| `.env`                        | Secrets and configuration        | No         | Yes      |

> **Backup note**: Back up `hitchhiker.img` (or the raw mount contents) along with
> `dex-config.yaml` and `.env`. The LUKS image is self-contained — restoring it to
> another machine requires only the passphrase.

## Security

See [`THREAT_MODEL.md`](THREAT_MODEL.md) for the full threat catalog and hardening
checklist.
