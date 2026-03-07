# User Guide

## Prerequisites

- AWS CLI configured with credentials for the target account
- Node.js (for CDK)
- Python 3.13
- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Setup

```bash
# Install CDK dependencies
cd infra
npm install

# Install Lambda dependencies
cd ../lambda
uv sync
```

## Deploying

```bash
cd infra
npx cdk deploy HsaReceiptArchiverStack
```

CDK handles everything: building the Lambda (including Ghostscript), creating AWS resources, and wiring permissions. The build runs in Docker to compile native dependencies.

### First-Time Setup (after initial deploy)

1. **Set the Anthropic API key** in SSM Parameter Store:
    ```bash
    aws ssm put-parameter \
        --name /hsa-receipt-archiver/anthropic-api-key \
        --value "sk-ant-..." \
        --type SecureString
    ```

2. **Set the allowed sender list** (comma-separated emails):
    ```bash
    aws ssm put-parameter \
        --name /hsa-receipt-archiver/allowed-senders \
        --value "you@example.com" \
        --type String
    ```

3. **Subscribe to SNS topics** to receive email notifications:
    ```bash
    # Main notifications (success, rejection, failure)
    aws sns subscribe \
        --topic-arn arn:aws:sns:us-east-1:ACCOUNT:hsa-receipt-archiver-notifications \
        --protocol email \
        --notification-endpoint you@example.com

    # Detailed failures (stack traces for debugging)
    aws sns subscribe \
        --topic-arn arn:aws:sns:us-east-1:ACCOUNT:hsa-receipt-archiver-detailed-failures \
        --protocol email \
        --notification-endpoint you@example.com
    ```

4. **Verify the SES domain** if not already done.

## Submitting Receipts

Email a receipt image (JPEG, PNG, GIF, WebP) or PDF as an attachment to your configured SES address. The system will:

- Analyze it with Claude for HSA eligibility
- Convert it to PDF/A and archive it in S3
- Update the CSV ledger
- Send you a notification with the result

### Force Storing a Receipt

If Claude incorrectly rejects a receipt, re-send the email with `FORCE_STORE` in the email body. This bypasses eligibility checks and archives the receipt regardless.

## Running Tests

```bash
cd lambda
uv run pytest              # all tests
uv run pytest -v           # verbose output
uv run pytest tests/test_handler.py  # specific file
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

This prints what Claude would return: eligibility, amounts, provider, dates, reasoning. Useful for debugging prompt issues or checking a receipt before submitting.

You can optionally pass `--model` to override the default model.

### Bulk Upload

Process a folder of receipts through the full Lambda pipeline (useful for initial migration):

```bash
cd lambda
uv run python scripts/bulk_upload.py /path/to/receipts/ \
    --bucket hsa-receipts-ACCOUNT-us-east-1 \
    --sender you@example.com
```

This wraps each file in a MIME email, uploads it to S3 as a raw email, and invokes the Lambda synchronously. Progress is printed for each file.

## Common S3 Operations

### Download the ledger

```bash
aws s3 cp s3://BUCKET/ledger/hsa-receipts.csv ./hsa-receipts.csv
```

### Upload an edited ledger

```bash
aws s3 cp ./hsa-receipts.csv s3://BUCKET/ledger/hsa-receipts.csv \
    --content-type text/csv
```

### List archived receipts

```bash
aws s3 ls s3://BUCKET/receipts/ --recursive
```

### Delete a file and all its versions

```bash
aws s3api list-object-versions \
    --bucket BUCKET \
    --prefix path/to/file \
    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
    --output json \
  | aws s3api delete-objects --bucket BUCKET --delete file:///dev/stdin
```

### Delete all objects under a prefix

```bash
aws s3 rm s3://BUCKET/some-prefix/ --recursive
```

## Checking Lambda Logs

```bash
aws logs tail /aws/lambda/hsa-receipt-archiver --follow
```

## Updating SSM Parameters

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

Note: SSM values are cached in the Lambda's memory. After updating a parameter, the Lambda will pick up the new value on its next cold start. To force a cold start, you can update the Lambda's configuration (e.g., change an environment variable and change it back) or wait for the existing execution environment to expire.

## Cost Monitoring

A $10/month AWS Budget is configured with alerts at 50%, 80%, and 100%. Alerts go to the `hsa-receipt-archiver-budget-alerts` SNS topic. Subscribe to it the same way as the notification topics.

The primary cost drivers are:
- Claude API calls (billed by Anthropic, not AWS)
- Lambda execution time
- S3 storage
- SNS email delivery
