import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { BudgetDynamoDbStack } from "../lib/budget-dynamodb-stack";

function createTestTemplate(stage: "dev" | "prod"): Template {
    const app = new cdk.App();
    const stack = new BudgetDynamoDbStack(app, "TestBudgetDynamoDbStack", {
        env: { account: "123456789012", region: "us-east-1" },
        stage,
    });
    return Template.fromStack(stack);
}

describe("BudgetDynamoDbStack", () => {
    describe("prod stage", () => {
        let template: Template;

        beforeAll(() => {
            template = createTestTemplate("prod");
        });

        test("creates four DynamoDB tables", () => {
            template.resourceCountIs("AWS::DynamoDB::Table", 4);
        });

        test("Category table has correct key schema", () => {
            template.hasResourceProperties("AWS::DynamoDB::Table", {
                TableName: "Category-prod",
                KeySchema: [{ AttributeName: "categoryId", KeyType: "HASH" }],
            });
        });

        test("Budget table has correct key schema", () => {
            template.hasResourceProperties("AWS::DynamoDB::Table", {
                TableName: "Budget-prod",
                KeySchema: [
                    { AttributeName: "yearMonth", KeyType: "HASH" },
                    { AttributeName: "categoryId", KeyType: "RANGE" },
                ],
            });
        });

        test("BudgetAuditLog table has correct key schema", () => {
            template.hasResourceProperties("AWS::DynamoDB::Table", {
                TableName: "BudgetAuditLog-prod",
                KeySchema: [
                    { AttributeName: "changedAtYearMonth", KeyType: "HASH" },
                    { AttributeName: "sortId", KeyType: "RANGE" },
                ],
            });
        });

        test("Transactions table has correct key schema", () => {
            template.hasResourceProperties("AWS::DynamoDB::Table", {
                TableName: "Transactions-prod",
                KeySchema: [
                    { AttributeName: "yearMonth", KeyType: "HASH" },
                    { AttributeName: "sortId", KeyType: "RANGE" },
                ],
            });
        });

        test("all tables use on-demand billing", () => {
            template.allResourcesProperties("AWS::DynamoDB::Table", {
                BillingMode: "PAY_PER_REQUEST",
            });
        });

        test("all tables have PITR enabled", () => {
            template.allResourcesProperties("AWS::DynamoDB::Table", {
                PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
            });
        });

        test("prod tables have RETAIN removal policy", () => {
            template.allResources("AWS::DynamoDB::Table", {
                UpdateReplacePolicy: "Retain",
                DeletionPolicy: "Retain",
            });
        });
    });

    describe("dev stage", () => {
        let template: Template;

        beforeAll(() => {
            template = createTestTemplate("dev");
        });

        test("dev tables use stage-suffixed names", () => {
            template.hasResourceProperties("AWS::DynamoDB::Table", {
                TableName: "Category-dev",
            });
            template.hasResourceProperties("AWS::DynamoDB::Table", {
                TableName: "Budget-dev",
            });
        });

        test("dev tables have DELETE removal policy", () => {
            template.allResources("AWS::DynamoDB::Table", {
                UpdateReplacePolicy: "Delete",
                DeletionPolicy: "Delete",
            });
        });
    });
});
