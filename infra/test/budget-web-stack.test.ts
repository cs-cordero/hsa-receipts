import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as route53 from "aws-cdk-lib/aws-route53";
import { Match, Template } from "aws-cdk-lib/assertions";
import { BudgetWebStack } from "../lib/budget-web-stack";

function createTestTemplate(stage: "dev" | "prod"): Template {
    const app = new cdk.App();
    const env = { account: "123456789012", region: "us-east-1" };

    const helperStack = new cdk.Stack(app, "HelperStack", { env });
    const userPool = new cognito.UserPool(helperStack, "UserPool");
    const budgetZone = new route53.HostedZone(helperStack, "BudgetZone", {
        zoneName: "budget.corderohq.com",
    });
    const budgetCertificate = new acm.Certificate(helperStack, "BudgetCert", {
        domainName: "budget.corderohq.com",
    });
    const categoryGroupTable = new dynamodb.Table(helperStack, "CategoryGroupTable", {
        partitionKey: { name: "groupId", type: dynamodb.AttributeType.STRING },
    });
    const categoryTable = new dynamodb.Table(helperStack, "CategoryTable", {
        partitionKey: { name: "categoryId", type: dynamodb.AttributeType.STRING },
    });
    const budgetTable = new dynamodb.Table(helperStack, "BudgetTable", {
        partitionKey: { name: "yearMonth", type: dynamodb.AttributeType.STRING },
        sortKey: { name: "categoryId", type: dynamodb.AttributeType.STRING },
    });
    const budgetAuditLogTable = new dynamodb.Table(helperStack, "BudgetAuditLogTable", {
        partitionKey: { name: "entityType", type: dynamodb.AttributeType.STRING },
        sortKey: { name: "sortId", type: dynamodb.AttributeType.STRING },
    });
    const transactionsTable = new dynamodb.Table(helperStack, "TransactionsTable", {
        partitionKey: { name: "yearMonth", type: dynamodb.AttributeType.STRING },
        sortKey: { name: "sortId", type: dynamodb.AttributeType.STRING },
    });

    const stack = new BudgetWebStack(app, "TestBudgetWebStack", {
        env,
        stage,
        userPool,
        budgetZone,
        budgetCertificate,
        categoryGroupTable,
        categoryTable,
        budgetTable,
        budgetAuditLogTable,
        transactionsTable,
    });

    return Template.fromStack(stack);
}

describe("BudgetWebStack", () => {
    describe("prod stage", () => {
        let template: Template;

        beforeAll(() => {
            template = createTestTemplate("prod");
        });

        test("creates a Cognito User Pool Client for budget app", () => {
            template.hasResourceProperties("AWS::Cognito::UserPoolClient", {
                ClientName: "budget-web-app-prod",
                AllowedOAuthFlows: ["code"],
            });
        });

        test("callback URL uses prod budget domain", () => {
            template.hasResourceProperties("AWS::Cognito::UserPoolClient", {
                CallbackURLs: ["https://budget.corderohq.com/callback"],
            });
        });

        test("creates a Lambda function", () => {
            template.hasResourceProperties("AWS::Lambda::Function", {
                FunctionName: "budget-handler-prod",
                Runtime: "python3.13",
                Handler: "corderohq.budget_handler.handler",
            });
        });

        test("Lambda has DynamoDB table name environment variables", () => {
            template.hasResourceProperties("AWS::Lambda::Function", {
                Environment: {
                    Variables: Match.objectLike({
                        CATEGORY_TABLE_NAME: Match.anyValue(),
                        BUDGET_TABLE_NAME: Match.anyValue(),
                        BUDGET_AUDIT_LOG_TABLE_NAME: Match.anyValue(),
                        TRANSACTIONS_TABLE_NAME: Match.anyValue(),
                        SSM_API_KEY_PARAM: "/budget/anthropic-api-key",
                    }),
                },
            });
        });

        test("creates an API Gateway HTTP API", () => {
            template.hasResourceProperties("AWS::ApiGatewayV2::Api", {
                Name: "budget-api-prod",
                ProtocolType: "HTTP",
            });
        });

        test("creates a CloudFront distribution with prod domain", () => {
            template.hasResourceProperties("AWS::CloudFront::Distribution", {
                DistributionConfig: Match.objectLike({
                    Aliases: ["budget.corderohq.com"],
                }),
            });
        });

        test("CloudFront has error responses for SPA routing", () => {
            template.hasResourceProperties("AWS::CloudFront::Distribution", {
                DistributionConfig: Match.objectLike({
                    CustomErrorResponses: Match.arrayWith([
                        Match.objectLike({
                            ErrorCode: 404,
                            ResponseCode: 200,
                            ResponsePagePath: "/index.html",
                        }),
                    ]),
                }),
            });
        });

        test("creates a Route 53 A record for the budget domain", () => {
            template.hasResourceProperties("AWS::Route53::RecordSet", {
                Name: "budget.corderohq.com.",
                Type: "A",
            });
        });

        test("Lambda has SSM GetParameter permission", () => {
            template.hasResourceProperties("AWS::IAM::Policy", {
                PolicyDocument: {
                    Statement: Match.arrayWith([
                        Match.objectLike({
                            Action: "ssm:GetParameter",
                            Resource: Match.objectLike({
                                "Fn::Join": Match.anyValue(),
                            }),
                        }),
                    ]),
                },
            });
        });
    });

    describe("dev stage", () => {
        let template: Template;

        beforeAll(() => {
            template = createTestTemplate("dev");
        });

        test("dev Lambda uses dev function name", () => {
            template.hasResourceProperties("AWS::Lambda::Function", {
                FunctionName: "budget-handler-dev",
            });
        });

        test("dev API Gateway uses dev name", () => {
            template.hasResourceProperties("AWS::ApiGatewayV2::Api", {
                Name: "budget-api-dev",
            });
        });

        test("dev CloudFront uses dev domain", () => {
            template.hasResourceProperties("AWS::CloudFront::Distribution", {
                DistributionConfig: Match.objectLike({
                    Aliases: ["dev.budget.corderohq.com"],
                }),
            });
        });

        test("dev callback URL uses dev budget domain", () => {
            template.hasResourceProperties("AWS::Cognito::UserPoolClient", {
                CallbackURLs: ["https://dev.budget.corderohq.com/callback"],
            });
        });

        test("dev Route 53 A record uses dev domain", () => {
            template.hasResourceProperties("AWS::Route53::RecordSet", {
                Name: "dev.budget.corderohq.com.",
                Type: "A",
            });
        });
    });
});
