#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { DnsStack } from "./lib/dns-stack";
import { HsaReceiptsStack } from "./lib/hsa-receipts-stack";
import { HsaWebStack } from "./lib/hsa-web-stack";
import { MathQuizStack } from "./lib/math-quiz-stack";
import { PersonalFinanceDynamoDbStack } from "./lib/personal-finance-dynamodb-stack";
import { PersonalFinanceWebStack } from "./lib/personal-finance-web-stack";
import { PlatformStack } from "./lib/platform-stack";
import type { Stage } from "./lib/constants";

const app = new cdk.App();

const env = {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "us-east-1",
};

// The single corderohq.com hosted zone. Deploys ahead of everything else — the shared
// certificate cannot finish DNS validation until this zone is authoritative in public DNS.
const dns = new DnsStack(app, "DnsStack", { env, terminationProtection: true });

const platform = new PlatformStack(app, "PlatformStack", {
    env,
    terminationProtection: true,
    rootZone: dns.rootZone,
});
platform.addDependency(dns);

const hsaReceipts = new HsaReceiptsStack(app, "HsaReceiptArchiverStack", {
    env,
    terminationProtection: true,
    rootZone: dns.rootZone,
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
    rootZone: dns.rootZone,
    certificate: platform.certificate,
});
hsaWeb.addDependency(platform);
hsaWeb.addDependency(hsaReceipts);

// Math quiz — a static page only. No API, no sign-in, no database.
const mathQuiz = new MathQuizStack(app, "MathQuizStack", {
    env,
    terminationProtection: true,
    rootZone: dns.rootZone,
    certificate: platform.certificate,
});
mathQuiz.addDependency(platform);

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
        rootZone: dns.rootZone,
        certificate: platform.certificate,
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
