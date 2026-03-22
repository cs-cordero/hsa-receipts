# User Guide

## Prerequisites

- AWS CLI configured with credentials for the target account
- Node.js (for CDK)
- Docker (for Lambda bundling during CDK deploy)
- Python 3.13
- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Setup

```bash
# Install CDK dependencies
cd infra
npm install

# Install Lambda dependencies
cd lambda
uv sync
```

## Deploying

```bash
cd infra
npx cdk deploy --all
```

CDK handles everything: building the Lambdas (including Ghostscript), creating AWS resources, deploying the web UI, and wiring permissions. The Lambda builds run in Docker to compile native dependencies.

The stacks deploy in order: PlatformStack first, then HsaReceiptArchiverStack, then HsaWebStack. To deploy a single stack without its dependencies, use `--exclusively`:

```bash
npx cdk deploy HsaWebStack --exclusively
```

### First-Time Setup (after initial deploy)

1. **Delegate DNS** from your registrar to Route 53. CDK creates hosted zones for your subdomains — copy the NS records from Route 53 into your registrar's DNS settings.

2. **Set the Anthropic API key** in SSM Parameter Store:
    ```bash
    aws ssm put-parameter \
        --name /hsa-receipt-archiver/anthropic-api-key \
        --value "sk-ant-..." \
        --type SecureString
    ```

3. **Set the allowed sender list** (comma-separated emails):
    ```bash
    aws ssm put-parameter \
        --name /hsa-receipt-archiver/allowed-senders \
        --value "you@example.com" \
        --type String
    ```

4. **Subscribe to SNS topics** to receive email notifications:
    ```bash
    # Main notifications (success, rejection, failure)
    aws sns subscribe \
        --topic-arn <notification-topic-arn> \
        --protocol email \
        --notification-endpoint you@example.com

    # Detailed failures (stack traces for debugging)
    aws sns subscribe \
        --topic-arn <detailed-failure-topic-arn> \
        --protocol email \
        --notification-endpoint you@example.com

    # Budget alerts
    aws sns subscribe \
        --topic-arn <budget-alerts-topic-arn> \
        --protocol email \
        --notification-endpoint you@example.com
    ```

    Find the topic ARNs in the AWS Console under SNS, or from `cdk deploy` output.

5. **Activate the SES receipt rule set**. CDK creates the rule set, but SES requires you to manually activate it in the AWS Console (SES > Email Receiving > Rule Sets).

6. **Create a Cognito user**. The user pool has self-signup disabled, so create users via the AWS Console or CLI:
    ```bash
    aws cognito-idp admin-create-user \
        --user-pool-id <pool-id> \
        --username you@example.com \
        --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
    ```
    You'll receive a temporary password by email. On first login, you'll set a new password and configure MFA (TOTP).

## Using the Web UI

Navigate to your configured domain in a browser. You'll be redirected to the login page on first visit.

### Ledger Editor

The home page shows the receipt ledger in a spreadsheet-style grid (powered by AG Grid). You can:

- Edit any cell directly
- Add new rows
- Delete selected rows
- Save changes back to S3

The "Unsaved changes" indicator appears when you have local edits that haven't been saved.

### Receipt Upload

Click "Upload" in the nav bar. Select a receipt file (PDF, JPEG, PNG, GIF, or WebP) and click "Upload & Analyze". The system will:

- Send the receipt to Claude for HSA eligibility analysis
- Display the extracted entries in a table
- Show any rejections with reasoning

Check "Force store" to bypass eligibility checks (useful when Claude incorrectly rejects a valid receipt).

## Submitting Receipts via Email

Email a receipt image or PDF as an attachment to your configured SES address. The system will process it and send you an SNS notification with the result.

To force-store a receipt that Claude rejects, re-send the email with `FORCE_STORE` in the email body.

## Running Tests

```bash
# Python (113 tests)
cd lambda
uv run pytest              # all tests
uv run pytest -v           # verbose output
uv run pytest tests/test_receipt_handler.py  # specific file

# TypeScript CDK (47 tests)
cd infra
npm test
```

## Linting and Formatting

### Python

```bash
cd lambda
uv run ruff check .        # lint
uv run ruff format .       # format
uv run ty check src/       # type check
```

### TypeScript

```bash
cd infra
npm run lint               # eslint
npm run format             # prettier
npm run typecheck          # tsc
```

## Scripts

### Dry Run

Test Claude's analysis on a receipt without storing anything:

```bash
cd lambda
uv run python scripts/dry_run.py /path/to/receipt.jpg --api-key sk-ant-...
```

Prints what Claude would return: eligibility, amounts, provider, dates, reasoning. Useful for debugging prompt issues or checking a receipt before submitting. Pass `--model` to override the default model.

### Bulk Upload

Process a folder of receipts through the full Lambda pipeline (useful for initial migration):

```bash
cd lambda
uv run python scripts/bulk_upload.py /path/to/receipts/ \
    --bucket <bucket-name> \
    --sender you@example.com
```

Wraps each file in a MIME email, uploads it to S3 as a raw email, and invokes the Lambda synchronously.

## Common Operations

### Checking Lambda Logs

```bash
aws logs tail /aws/lambda/hsa-receipt-archiver --follow
aws logs tail /aws/lambda/hsa-web-handler --follow
```

### Updating SSM Parameters

```bash
# Update allowed senders
aws ssm put-parameter \
    --name /hsa-receipt-archiver/allowed-senders \
    --value "user1@example.com,user2@example.com" \
    --type String \
    --overwrite

# Rotate API key
aws ssm put-parameter \
    --name /hsa-receipt-archiver/anthropic-api-key \
    --value "sk-ant-new-key" \
    --type SecureString \
    --overwrite
```

Note: SSM values are cached in the Lambda's memory. After updating a parameter, the Lambda will pick up the new value on its next cold start. To force a cold start, update any Lambda environment variable (e.g., add and remove a dummy variable).

### S3 Operations

```bash
# Download the ledger
aws s3 cp s3://BUCKET/ledger/hsa-receipts.csv ./hsa-receipts.csv

# List archived receipts
aws s3 ls s3://BUCKET/receipts/ --recursive
```

## Cost Monitoring

A monthly AWS Budget is configured with alerts at 50%, 80%, and 100% of the budget limit. Alerts go to an SNS topic — subscribe to it the same way as the notification topics.

The primary cost drivers are:
- Claude API calls (billed by Anthropic, not AWS)
- Lambda execution time
- S3 storage
- SNS email delivery
