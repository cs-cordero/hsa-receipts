import * as cdk from "aws-cdk-lib";
import type { Construct } from "constructs";

export class HsaReceiptsStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "hsa-receipts");

        // TODO: S3 bucket (7-day lifecycle on raw emails, permanent for receipts/ledger)

        // TODO: DynamoDB table (rate limiting)

        // TODO: Lambda function (Python 3.13, 1GB RAM, 5min timeout, concurrency=2)

        // TODO: SES receipt rule set

        // TODO: CloudWatch log group (7-day retention)

        // TODO: IAM roles/permissions

        // TODO: Budget alerts ($5, $8, $10)
    }
}
