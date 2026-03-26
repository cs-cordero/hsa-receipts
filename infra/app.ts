#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { BudgetDynamoDbStack } from "./lib/budget-dynamodb-stack";
import { BudgetWebStack } from "./lib/budget-web-stack";
import { HsaReceiptsStack } from "./lib/hsa-receipts-stack";
import { HsaWebStack } from "./lib/hsa-web-stack";
import { PlatformStack } from "./lib/platform-stack";
import type { Stage } from "./lib/constants";

const app = new cdk.App();

const env = {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "us-east-1",
};

const platform = new PlatformStack(app, "PlatformStack", { env, terminationProtection: true });

const hsaReceipts = new HsaReceiptsStack(app, "HsaReceiptArchiverStack", {
    env,
    terminationProtection: true,
    hsaZone: platform.hsaZone,
});
hsaReceipts.addDependency(platform);

const hsaWeb = new HsaWebStack(app, "HsaWebStack", {
    env,
    terminationProtection: true,
    userPool: platform.userPool,
    assetsBucket: platform.assetsBucket,
    distribution: platform.distribution,
    dataBucket: hsaReceipts.bucket,
    processorFunction: hsaReceipts.handler,
    hsaZone: platform.hsaZone,
    hsaCertificate: platform.hsaCertificate,
});
hsaWeb.addDependency(platform);
hsaWeb.addDependency(hsaReceipts);

<<<<<<< Updated upstream
// Budget app — instantiate for each stage
function createBudgetStacks(stage: Stage): void {
    const suffix = `-${stage}`;

    const budgetData = new BudgetDynamoDbStack(app, `BudgetDynamoDbStack${suffix}`, {
=======
// Personal finance app — instantiate for each stage. Prod stacks carry termination
// protection so an accidental `cdk destroy` can't wipe the live data or user pool client.
function createPersonalFinanceStacks(stage: Stage): void {
    const prefix = `PersonalFinance-${stage}`;
    const terminationProtection = stage === "prod";

    const data = new PersonalFinanceDynamoDbStack(app, `${prefix}-DynamoDbStack`, {
>>>>>>> Stashed changes
        env,
        stage,
        terminationProtection,
    });
    budgetData.addDependency(platform);

<<<<<<< Updated upstream
    const budgetWeb = new BudgetWebStack(app, `BudgetWebStack${suffix}`, {
=======
    const web = new PersonalFinanceWebStack(app, `${prefix}-WebStack`, {
>>>>>>> Stashed changes
        env,
        stage,
        terminationProtection,
        userPool: platform.userPool,
        budgetZone: platform.budgetZone,
        budgetCertificate: platform.budgetCertificate,
        categoryGroupTable: budgetData.categoryGroupTable,
        categoryTable: budgetData.categoryTable,
        budgetTable: budgetData.budgetTable,
        budgetAuditLogTable: budgetData.budgetAuditLogTable,
        transactionsTable: budgetData.transactionsTable,
    });
    budgetWeb.addDependency(platform);
    budgetWeb.addDependency(budgetData);
}

createBudgetStacks("prod");
createBudgetStacks("dev");
