# Architecture

## What This Project Does

This is an automated HSA (Health Savings Account) receipt archiving system. There are two ways to submit receipts:

1. **Email**: Send a receipt photo or PDF to a dedicated email address. The system processes it automatically and sends a notification with the result.
2. **Web UI**: Log in to the web app, upload a receipt, and see the extracted data immediately. The web UI also provides a spreadsheet-style ledger editor.

In both cases, the system:

1. Validates the receipt (email auth checks for email submissions)
2. Sends the receipt to Claude AI for HSA eligibility analysis
3. Converts the receipt to PDF/A format for long-term archival
4. Stores the PDF in S3 with a structured naming convention
5. Appends a row to a CSV ledger tracking all receipts
6. Reports the result (SNS notification for email, HTTP response for web)

## Project Layout

```
hsa-receipts/
    infra/           AWS CDK infrastructure (TypeScript)
    lambda/          Lambda function code (Python 3.13)
        src/         Source code
        tests/       Unit tests
        scripts/     Utility scripts (bulk upload, dry run)
    web/             Static web UI (HTML/CSS/JS)
    docs/            Documentation
```

## Infrastructure Overview

The infrastructure is split into three CDK stacks, deployed in order:

### PlatformStack

Shared platform resources used by all apps. Manages DNS zones (delegated from the registrar), TLS certificates, a Cognito user pool for authentication, an S3 bucket for static web assets, and a CloudFront distribution that serves the web UI with clean URL routing.

### HsaReceiptArchiverStack

The email-based receipt processing pipeline. Includes an S3 bucket for receipt data, the receipt processor Lambda (bundles Ghostscript for PDF/A conversion), SES receipt rules to receive inbound email, SNS topics for notifications, DNS records for email delivery, and a monthly budget with cost alerts.

### HsaWebStack

The web application layer. Creates a Cognito app client, an API Gateway HTTP API with JWT-based authorization, a lightweight Lambda for the web API, and deploys the static frontend to the shared assets bucket with CloudFront cache invalidation.

### How They Connect

```
PlatformStack (DNS, TLS, Cognito, CloudFront, S3 assets)
    |
    +-- HsaReceiptArchiverStack (SES, receipt processing Lambda, data S3 bucket)
    |       |
    +-------+-- HsaWebStack (API Gateway, web Lambda, static site deployment)
```

The web stack depends on both other stacks: it uses the platform's auth and hosting infrastructure, and it invokes the receipt processor Lambda and reads/writes the data bucket from the receipt stack.

## Email Processing Flow

```
Email --> SES --> S3 (raw-emails/) + Lambda
                        |
                  Lambda processes:
                    1. Validate email auth (SPF/DKIM)
                    2. Check sender against allow list
                    3. Send attachments to Claude for analysis
                    4. Convert eligible receipts to PDF/A
                    5. Store in S3 (receipts/{year}/...)
                    6. Update CSV ledger
                    7. Send SNS notification
```

## Web Application Flow

```
Browser --> CloudFront --> S3 (static HTML/CSS/JS)
                |
                +--> API Gateway --> Lambda (web handler)
                      (JWT auth)        |
                                   GET /ledger  --> read CSV from S3
                                   PUT /ledger  --> write CSV to S3
                                   POST /receipt --> invoke processor Lambda
```

The web UI uses Cognito's hosted login page with PKCE for authentication. After login, the browser gets tokens and sends them as Bearer tokens to the API.

## Source Code Structure

### `lambda/src/hsa_receipt_archiver/`

```
receipt_handler.py      Receipt processing entrypoint (email + web uploads)
web_handler.py          Web API entrypoint (GET/PUT /ledger, POST /receipt)
claude_client.py        Claude API integration for HSA eligibility
util.py                 Shared utilities (get_env_var, parse_date, today)

aws/                    AWS service wrappers
    s3.py               S3 operations (receipts, ledger, raw emails)
    ses.py              SES email parsing and attachment extraction
    sns.py              SNS notifications (success, rejection, failure)
    ssm.py              SSM Parameter Store (API key, allowed senders)

archiver/               Core archiving logic
    ledger.py           CSV ledger management with duplicate detection
    pdf.py              PDF/A conversion and page extraction via Ghostscript
```

### `web/`

```
index.html              Main page (ledger editor)
upload.html             Receipt upload page
callback.html           OAuth callback handler
config.js               Environment configuration (domains, client ID)
auth.js                 Authentication logic (login, token management)
ledger.js               Spreadsheet-style ledger editor (AG Grid)
upload.js               Receipt upload and results display
styles.css              Shared styles
```

### Receipt Processing (`receipt_handler.py`)

`process_receipt` is the Lambda entrypoint. It handles two event types:

- **SES events** (email): Extracts the SES record, checks SPF/DKIM verdicts, fetches the raw email from S3, validates the sender against an allow list, then processes each attachment.
- **Web events** (upload): Fetches the uploaded file from S3 and processes it directly.

For each attachment, it sends the content to Claude for HSA analysis, filters by eligibility (unless force-store is enabled), converts to PDF/A, stores in S3, and updates the ledger.

### Web API (`web_handler.py`)

`handle` is the Lambda entrypoint for the HTTP API. It routes by method and path:

- **GET /ledger**: Returns the CSV ledger from S3 (or an empty ledger if none exists).
- **PUT /ledger**: Replaces the CSV ledger in S3 with the request body.
- **POST /receipt**: Accepts a base64-encoded file, stores it in S3, invokes the processor Lambda synchronously, and returns the extracted entries and rejections.

### Claude Integration (`claude_client.py`)

Uses Claude Haiku for cost efficiency. The system prompt instructs Claude to extract each out-of-pocket transaction separately, focusing on patient responsibility (copays, coinsurance, deductibles) and excluding insurance payments or adjustments.

Each result includes: eligibility, description, category, amount, provider, dates, patient, and reasoning.

Multi-page PDFs (3-10 pages) are split into individual pages and analyzed separately. PDFs over 10 pages are rejected.

### PDF/A Conversion (`archiver/pdf.py`)

Uses Ghostscript (bundled with the Lambda) to produce PDF/A-2b output. Images are first converted to PDF via Pillow at 300 DPI, then run through Ghostscript. PDFs go directly through Ghostscript.

### Ledger (`archiver/ledger.py`)

A CSV file stored in S3. Columns: Id, Service Date, Payment Date, Vendor/Provider, Patient/For, Category, Description, Amount, Receipt S3 URI, Reimbursed, Notes, Prob. of Duplicate.

New entries get an auto-incremented ID and a duplicate probability score (0-100) based on matching provider, amount, and service date against existing entries.

## Environment Variables

### Receipt Processor Lambda

| Variable | Purpose |
|---|---|
| `BUCKET_NAME` | S3 bucket for receipt data |
| `SSM_API_KEY_PARAM` | SSM path to Anthropic API key |
| `SSM_ALLOWED_SENDERS_PARAM` | SSM path to allowed sender list |
| `SNS_TOPIC_ARN` | Main notification topic |
| `SNS_DETAILED_FAILURE_TOPIC_ARN` | Detailed failure topic |
| `LD_LIBRARY_PATH` | Ghostscript shared libraries |
| `GS_LIB` | Ghostscript resource files |

### Web Handler Lambda

| Variable | Purpose |
|---|---|
| `BUCKET_NAME` | S3 bucket for receipt data |
| `PROCESSOR_FUNCTION_NAME` | Receipt processor Lambda to invoke |

All env vars are accessed via `get_env_var()` which raises if missing or blank.

## Testing

- **Python**: 113 unit tests across 9 test files. All AWS calls are mocked. Run with `uv run pytest`.
- **TypeScript**: 47 CDK tests across 2 test files. Run with `cd infra && npm test`.

Test fixtures in `conftest.py` set dummy AWS credentials and SNS topic ARNs so module-level `boto3.client()` calls don't fail during import.

## Key Design Decisions

- **Three stacks**: Separates shared platform (DNS, auth, CDN) from the receipt pipeline and the web app, allowing independent updates.
- **Haiku model**: Balances cost and quality for receipt analysis.
- **PDF/A-2b**: Archival-grade format for long-term storage.
- **CSV ledger**: Simple, portable, human-editable. No database needed.
- **Per-page PDF splitting**: Avoids Claude's context limitations on large documents.
- **FORCE_STORE**: Escape hatch when Claude incorrectly rejects a receipt.
- **SPF/DKIM enforcement**: Prevents email spoofing attacks.
- **S3 versioning**: Protects against accidental ledger overwrites.
- **Ghostscript bundling**: Included in Lambda deployment (not a Lambda layer) for simpler management.
- **PKCE auth flow**: Secure browser-based OAuth without a client secret.
- **CloudFront Function for URL rewriting**: Enables clean URLs (e.g., `/upload` instead of `/upload.html`) without server-side routing.
