import * as cdk from "aws-cdk-lib";
import * as budgets from "aws-cdk-lib/aws-budgets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sesActions from "aws-cdk-lib/aws-ses-actions";
import * as sns from "aws-cdk-lib/aws-sns";
import type { Construct } from "constructs";

const DOMAIN_NAME = "hsa.corderohq.com";

export class HsaReceiptArchiverStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "hsa-receipt-archiver");

        // S3 Bucket
        const bucket = new s3.Bucket(this, "ReceiptsBucket", {
            bucketName: `hsa-receipts-${this.account}-${this.region}`,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: cdk.RemovalPolicy.RETAIN,
            lifecycleRules: [
                {
                    prefix: "raw-emails/",
                    tagFilters: { status: "processed" },
                    expiration: cdk.Duration.days(7),
                },
                {
                    prefix: "raw-emails/",
                    expiration: cdk.Duration.days(30),
                },
            ],
        });

        // CloudWatch Log Group
        const logGroup = new logs.LogGroup(this, "LambdaLogGroup", {
            logGroupName: "/aws/lambda/hsa-receipt-archiver",
            retention: logs.RetentionDays.ONE_MONTH,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
        });

        // Lambda Function
        const handler = new lambda.Function(this, "ReceiptArchiver", {
            functionName: "hsa-receipt-archiver",
            runtime: lambda.Runtime.PYTHON_3_13,
            handler: "hsa_receipt_archiver.handler.process_receipt",
            code: lambda.Code.fromAsset("../lambda", {
                bundling: {
                    image: lambda.Runtime.PYTHON_3_13.bundlingImage,
                    command: [
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -r src/hsa_receipt_archiver /asset-output/",
                    ],
                },
            }),
            memorySize: 1024,
            timeout: cdk.Duration.minutes(5),
            reservedConcurrentExecutions: 2,
            logGroup,
            environment: {
                BUCKET_NAME: bucket.bucketName,
                DOMAIN_NAME,
                SSM_API_KEY_PARAM: "/hsa-receipt-archiver/anthropic-api-key",
                SSM_ALLOWED_SENDERS_PARAM: "/hsa-receipt-archiver/allowed-senders",
            },
        });

        // IAM Permissions
        bucket.grantReadWrite(handler);

        handler.addToRolePolicy(
            new iam.PolicyStatement({
                actions: ["ssm:GetParameter"],
                resources: [
                    cdk.Arn.format(
                        {
                            service: "ssm",
                            resource: "parameter",
                            resourceName: "hsa-receipt-archiver/*",
                        },
                        this,
                    ),
                ],
            }),
        );

        handler.addToRolePolicy(
            new iam.PolicyStatement({
                actions: ["ses:SendEmail", "ses:SendRawEmail"],
                resources: ["*"],
            }),
        );

        // SES Receipt Rule Set + Rule
        const ruleSet = new ses.ReceiptRuleSet(this, "ReceiptRuleSet", {
            receiptRuleSetName: "hsa-receipt-archiver",
        });

        ruleSet.addRule("ReceiptRule", {
            recipients: [`receipts@${DOMAIN_NAME}`],
            actions: [
                new sesActions.S3({
                    bucket,
                    objectKeyPrefix: "raw-emails/",
                }),
                new sesActions.Lambda({
                    function: handler,
                }),
            ],
        });

        // Budget Alerts via SNS
        const budgetTopic = new sns.Topic(this, "BudgetAlertsTopic", {
            topicName: "hsa-receipt-archiver-budget-alerts",
        });

        budgetTopic.addToResourcePolicy(
            new iam.PolicyStatement({
                actions: ["sns:Publish"],
                principals: [new iam.ServicePrincipal("budgets.amazonaws.com")],
                resources: [budgetTopic.topicArn],
            }),
        );

        const budgetThresholdPercentages = [50, 80, 100];

        new budgets.CfnBudget(this, "MonthlyBudget", {
            budget: {
                budgetName: "hsa-receipt-archiver-monthly",
                budgetType: "COST",
                timeUnit: "MONTHLY",
                budgetLimit: {
                    amount: 10,
                    unit: "USD",
                },
            },
            notificationsWithSubscribers: budgetThresholdPercentages.map((pct) => ({
                notification: {
                    notificationType: "ACTUAL",
                    comparisonOperator: "GREATER_THAN",
                    threshold: pct,
                    thresholdType: "PERCENTAGE",
                },
                subscribers: [
                    {
                        subscriptionType: "SNS",
                        address: budgetTopic.topicArn,
                    },
                ],
            })),
        });
    }
}
