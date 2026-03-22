# HSA Receipt Archiver

Automated HSA receipt processing and archival. Receipts can be submitted via email or a web UI, and the system validates HSA eligibility using Claude AI, converts documents to PDF/A for long-term storage, and maintains a CSV ledger of all entries.

See `docs/architecture.md` for how the system works and `docs/user_guide.md` for setup and usage.

## Project Structure

```
infra/       AWS CDK infrastructure (TypeScript)
lambda/      Lambda functions (Python 3.13)
web/         Static web UI (HTML/CSS/JS)
docs/        Documentation
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
