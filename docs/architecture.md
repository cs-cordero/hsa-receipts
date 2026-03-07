# Architecture

## What This Project Does

This is an automated HSA (Health Savings Account) receipt archiving system. You email a receipt photo or PDF to a dedicated address, and the system:

1. Validates the email (SPF/DKIM, sender whitelist)
2. Sends the receipt to Claude AI for HSA eligibility analysis
3. Converts the receipt to PDF/A format for long-term archival
4. Stores the PDF in S3 with a structured naming convention
5. Appends a row to a CSV ledger tracking all receipts
6. Sends an SNS notification with the result

## Project Layout

```
hsa-receipts/
    infra/           AWS CDK infrastructure (TypeScript)
    lambda/          Lambda function code (Python 3.13)
        src/         Source code
        tests/       Unit tests (82 tests)
        scripts/     Utility scripts (bulk upload, dry run)
    docs/            Documentation
```

## AWS Services

```
Email --> SES --> S3 (raw-emails/) + Lambda
                        |
                  Lambda processes:
                    1. Validate email auth
                    2. Claude analyzes receipt
                    3. Convert to PDF/A
                    4. Store in S3 (receipts/)
                    5. Update CSV ledger
                    6. Send SNS notification
```

- **SES** receives emails at the configured domain, saves raw email to S3, then invokes Lambda.
- **S3** stores raw emails (temporary), archived receipts (permanent), and the CSV ledger. Versioning is enabled. Raw emails expire after 7 days (processed) or 30 days (unprocessed).
- **Lambda** runs the processing pipeline. Python 3.13, 1024 MB memory, 5-minute timeout. Bundles Ghostscript for PDF/A conversion.
- **SNS** has three topics: `notifications` (success/rejection/failure), `detailed-failures` (stack traces), and `budget-alerts` (cost monitoring).
- **SSM Parameter Store** holds the Anthropic API key (encrypted) and the allowed sender list.
- **AWS Budgets** alerts at 50%, 80%, and 100% of a $10/month limit.

## Source Code Structure

### `lambda/src/hsa_receipt_archiver/`

```
handler.py              Main Lambda entrypoint and orchestration
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

### Handler Flow (`handler.py`)

`process_receipt` is the Lambda entrypoint. It delegates to `_handle`, which:

1. Extracts the SES event record and message ID.
2. Checks SPF and DKIM verdicts (both must be PASS).
3. Fetches the raw email from S3 and parses it.
4. Validates the sender against the allowed list (from SSM).
5. Iterates through attachments, calling `_process_attachment` for each.
6. Tags the raw email as processed (triggers 7-day expiry).

`_process_attachment` handles a single attachment:

1. Calls `_analyze_receipt` which sends to Claude (splitting multi-page PDFs as needed).
2. Filters results by eligibility (unless `FORCE_STORE` is in the email body).
3. Converts to PDF/A.
4. Stores the PDF in S3: `receipts/{year}/{date}_{provider}_{description}.pdf`.
5. Adds each eligible item to the CSV ledger with duplicate scoring.
6. Sends an SNS success notification.

### Claude Integration (`claude_client.py`)

Uses `claude-haiku-4-5-20251001` for cost efficiency. The system prompt instructs Claude to:

- Extract each out-of-pocket transaction separately
- Focus only on patient responsibility (copays, coinsurance, deductibles)
- Exclude insurance payments, plan discounts, adjustments
- Return a JSON array of results

Each result includes: `is_eligible`, `description`, `short_description`, `category`, `amount`, `provider`, `service_date`, `payment_date`, `patient`, `reasoning`.

Results are post-validated: if `amount`, `provider`, or both dates are missing, the item is marked ineligible.

Multi-page PDFs (3-10 pages) are split into individual pages and analyzed separately. PDFs over 10 pages are rejected.

### PDF/A Conversion (`archiver/pdf.py`)

Uses Ghostscript (bundled binary) to produce PDF/A-2b output:

- Images are first converted to PDF via Pillow at 300 DPI, then run through Ghostscript.
- PDFs go directly through Ghostscript.
- Also provides `get_page_count` and `extract_page` for multi-page handling.

### Ledger (`archiver/ledger.py`)

A CSV file stored at `ledger/hsa-receipts.csv` in S3. Columns:

```
Id, Service Date, Payment Date, Vendor/Provider, Patient/For, Category,
Description, Amount, Receipt S3 URI, Reimbursed, Notes, Prob. of Duplicate
```

- **Id** auto-increments from the max existing ID.
- **Reimbursed** defaults to "No" (manually updated).
- **Prob. of Duplicate** is a 0-100 score: +30 for same provider, +30 for same amount, +40 for same date (or +20 within 30 days).

### SNS Notifications (`aws/sns.py`)

Four notification types:

- **Success**: formatted table of archived entries with provider, dates, amount, category, S3 URI.
- **Failure**: generic error with troubleshooting guidance.
- **Rejection**: explains why an item wasn't eligible, mentions `FORCE_STORE`.
- **Detailed failure**: full exception type, message, and stack trace (separate topic).

## Environment Variables

The Lambda function requires:

| Variable | Source | Purpose |
|---|---|---|
| `BUCKET_NAME` | CDK | S3 bucket name |
| `SSM_API_KEY_PARAM` | CDK | SSM path to Anthropic API key |
| `SSM_ALLOWED_SENDERS_PARAM` | CDK | SSM path to allowed sender list |
| `SNS_TOPIC_ARN` | CDK | Main notification topic |
| `SNS_DETAILED_FAILURE_TOPIC_ARN` | CDK | Detailed failure topic |
| `LD_LIBRARY_PATH` | CDK | Ghostscript shared libraries |
| `GS_LIB` | CDK | Ghostscript resource files |

All env vars sourced from `os.environ` use `get_env_var()` which raises if missing or blank.

## Infrastructure (`infra/lib/stack.ts`)

The CDK stack creates all resources in a single stack. The Lambda function is built from the `lambda/` directory using CDK's Python bundling, which runs in a Docker container to install dependencies and bundle the Ghostscript binary with its shared libraries.

## Testing

82 unit tests in `lambda/tests/`. All AWS calls are mocked. Run with `uv run pytest`.

Test fixtures in `conftest.py` set dummy AWS credentials and SNS topic ARNs so module-level `boto3.client()` calls don't fail during import.

## Key Design Decisions

- **Haiku model**: balances cost and quality for receipt analysis.
- **PDF/A-2b**: archival-grade format for long-term storage.
- **CSV ledger**: simple, portable, human-editable. No database needed.
- **Per-page PDF splitting**: avoids Claude's context limitations on large documents.
- **FORCE_STORE**: escape hatch when Claude incorrectly rejects a receipt.
- **SPF/DKIM enforcement**: prevents email spoofing attacks.
- **S3 versioning**: protects against accidental ledger overwrites.
- **Ghostscript bundling**: included in Lambda deployment (not a Lambda layer) for simpler management.
