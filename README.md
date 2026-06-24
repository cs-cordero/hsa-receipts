# corderohq

Personal household tools built on AWS, managed as a single monorepo.

## Apps

### HSA Receipt Archiver

Automated HSA receipt processing and archival. Receipts can be submitted via email or a web UI. The system validates HSA eligibility using Claude AI, converts documents to PDF/A for long-term storage, and maintains a CSV ledger of all entries.

- **Web UI**: Upload receipts, review Claude's analysis, and manage a spreadsheet-style ledger
- **Email pipeline**: Send receipts as attachments to a dedicated SES address for hands-free processing
- **Live at**: `hsa.corderohq.com`

### Personal Finance

A personal finance app for the family. Today the only feature is a monthly budgeting tool — track monthly spending against category-level targets, upload bank/credit card CSV exports, Claude auto-categorizes each transaction. Future features (e.g. Monte Carlo net worth simulation) will live in this same app.

- **Categories**: Create and manage budget categories with full audit history
- **Monthly targets**: Set per-category spending targets, carried forward month to month
- **CSV import**: Upload transaction exports; Claude maps columns and categorizes line items
- **Summary**: Budget vs. actuals view by month
- **Live at**: `finance.corderohq.com`

## Project Structure

```
infra/             AWS CDK infrastructure (TypeScript)
lambda/            Lambda functions (Python 3.13)
web/               HSA Receipt Archiver static web UI (HTML/CSS/JS)
personal-finance/  Personal Finance frontend (React + Vite + TypeScript)
docs/              Documentation
```

## Quick Start

```bash
# Install CDK dependencies
cd infra && npm install

# Install Lambda dependencies
cd lambda && uv sync

# Run tests
cd lambda && uv run pytest
cd infra && npm test

# Deploy
cd infra && npx cdk deploy --all
```

## Linting & Type Checking

```bash
# Python
cd lambda
uv run ruff check .
uv run ruff format --check .
uv run ty check src/

# TypeScript
cd infra
npx eslint .
npx prettier --check .
npx tsc --noEmit
```

## Documentation

See `docs/hsa-architecture.md` (HSA receipts app) and `docs/personal-finance-architecture.md` (personal finance app) for infrastructure details, and `docs/user_guide.md` for setup, deployment, and day-to-day usage.
