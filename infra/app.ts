#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { HsaReceiptsStack } from "./lib/hsa-receipts-stack";
import { HsaWebStack } from "./lib/hsa-web-stack";
import { PersonalFinanceDynamoDbStack } from "./lib/personal-finance-dynamodb-stack";
import { PersonalFinanceWebStack } from "./lib/personal-finance-web-stack";
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

// Personal finance app — instantiate for each stage. Prod stacks carry termination
// protection so an accidental `cdk destroy` can't wipe the live data or user pool client.
function createPersonalFinanceStacks(stage: Stage): void {
    const prefix = `PersonalFinance-${stage}`;
    const terminationProtection = stage === "prod";

    const data = new PersonalFinanceDynamoDbStack(app, `${prefix}-DynamoDbStack`, {
        env,
        stage,
        terminationProtection,
    });
    data.addDependency(platform);

    const web = new PersonalFinanceWebStack(app, `${prefix}-WebStack`, {
        env,
        stage,
        terminationProtection,
        userPool: platform.userPool,
        personalFinanceZone: platform.personalFinanceZone,
        personalFinanceCertificate: platform.personalFinanceCertificate,
        categoryGroupTable: data.categoryGroupTable,
        categoryTable: data.categoryTable,
        budgetTable: data.budgetTable,
        budgetAuditLogTable: data.budgetAuditLogTable,
        transactionsTable: data.transactionsTable,
        profileTable: data.profileTable,
        accountTable: data.accountTable,
        netWorthSnapshotTable: data.netWorthSnapshotTable,
    });
    web.addDependency(platform);
    web.addDependency(data);
}

createPersonalFinanceStacks("prod");
createPersonalFinanceStacks("dev");
