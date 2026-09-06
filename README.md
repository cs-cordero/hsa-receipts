# corderohq

Personal tools for the Cordero family. They all run on AWS. One repository holds them all.

## Apps

### HSA Receipt Archiver — [hsa.corderohq.com](https://hsa.corderohq.com)

The app keeps HSA receipts for many years. You send a receipt by email, or you upload it in the
web UI. Claude reads each receipt and decides if it is eligible. The app then converts the
document to PDF/A and adds a line to a CSV ledger.

- **Web UI** — Upload a receipt, read the result from Claude, and edit the ledger.
- **Email** — Send a receipt as an attachment to the SES address. No other step is necessary.

### Personal Finance — [finance.corderohq.com](https://finance.corderohq.com)

A finance app for the family. It has two features today: a monthly budget, and a net worth record.

- **Categories** — Make and change budget categories. The app keeps a full audit history.
- **Monthly targets** — Set a target for each category. The app carries each target forward.
- **Transactions** — Upload a CSV export from a bank or a credit card. Claude maps the columns
  and gives a category to each line.
- **Summary** — Compare the budget with the actual amounts, one month at a time.
- **Accounts and net worth** — Record a balance for each account. See the total over time.

This app has two stages, `dev` and `prod`. The dev app is at `dev.finance.corderohq.com`.

### Math Quiz — [math.corderohq.com](https://math.corderohq.com)

A practice page for times tables, addition, and subtraction. It needs no sign-in. It keeps the
high scores in the browser, and it sends nothing to a server.

### Landing page — [corderohq.com](https://corderohq.com)

One page for the domain itself. `www.corderohq.com` returns a 301 redirect to it.

## Infrastructure

Two facts about this account are unusual, and both are deliberate.

**One hosted zone.** `corderohq.com` holds every DNS record. No subdomain has a zone of its own.

**One certificate.** A single ACM certificate covers every hostname, through these five names:
`corderohq.com`, `*.corderohq.com`, `auth.corderohq.com`, `*.hsa.corderohq.com`, and
`*.finance.corderohq.com`.

The CDK app makes nine stacks:

| Stack | What it holds |
| --- | --- |
| `DnsStack` | The hosted zone. Deploy this one first. |
| `PlatformStack` | The shared certificate, the Cognito user pool, the landing page, and the HSA distribution |
| `HsaReceiptArchiverStack` | SES receipt rules, the receipt Lambda, and the data bucket |
| `HsaWebStack` | The HSA API and the HSA web assets |
| `MathQuizStack` | The math page, its bucket, and its distribution |
| `PersonalFinance-{dev,prod}-DynamoDbStack` | The tables for each stage |
| `PersonalFinance-{dev,prod}-WebStack` | The API, the Lambda, and the frontend for each stage |

## Project Structure

```
infra/                     AWS CDK infrastructure (TypeScript)
lambda/                    Lambda functions (Python 3.13)
web/                       All frontend source
    hsa/                   HSA Receipt Archiver web UI (HTML/CSS/JS)
    root/                  corderohq.com landing page (HTML/CSS)
    math/                  Math quiz page (HTML/CSS/JS)
    personal-finance/      Personal Finance frontend (React + Vite + TypeScript)
    shared/                Assets that every frontend uses (the favicon)
docs/                      Documentation
```

Each frontend reads the favicon from `web/shared/` through a symlink. Change that one file and
every app changes.

## Quick Start

```bash
# CDK dependencies
cd infra && npm install

# Lambda dependencies
cd lambda && uv sync

# Personal finance frontend dependencies
cd web/personal-finance && npm install
```

## Tests

```bash
cd lambda && uv run pytest
cd infra && npm test
```

## Deploy

**Build the personal finance frontend first.** Its stack deploys `web/personal-finance/dist`, and
not the source. If you skip the build, the deploy sends the previous build again.

```bash
cd web/personal-finance && npm run build
cd ../../infra && npx cdk deploy --all
```

The other three frontends need no build step. Their stacks upload the source folder directly.

For a new AWS account, read `docs/user_guide.md` before you deploy. `DnsStack` must be
authoritative in public DNS first. Until it is, the shared certificate cannot complete its DNS
validation, and the deploy waits.

## Lint and type checks

```bash
# Python
cd lambda
uv run ruff check .
uv run ruff format --check .
uv run ty check src/

# CDK
cd infra
npx eslint .
npx prettier --check .
npx tsc --noEmit

# Personal finance frontend
cd web/personal-finance
npm run lint
npm run format:check
```

## Documentation

- `docs/hsa-architecture.md` — the HSA receipts app
- `docs/personal-finance-architecture.md` — the personal finance app
- `docs/user_guide.md` — setup, deploy steps, and daily use
