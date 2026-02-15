# HSA Receipt Processor

Automated HSA receipt processing via email. Send a receipt photo and it gets validated for HSA eligibility, converted to PDF/A, and added to a ledger.

## Project Structure

- `infra/` — AWS CDK stack (TypeScript)
- `lambda/` — Lambda function code (Python 3.13)

## Setup

### Lambda (Python)

```bash
cd lambda
uv sync
```

### Infrastructure (CDK)

```bash
cd infra
npm install
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
