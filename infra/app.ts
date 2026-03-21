#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { HsaReceiptsStack } from "./lib/hsa-receipts-stack";
import { HsaWebStack } from "./lib/hsa-web-stack";
import { PlatformStack } from "./lib/platform-stack";

const app = new cdk.App();

const env = {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "us-east-1",
};

const platform = new PlatformStack(app, "PlatformStack", { env });

const hsaReceipts = new HsaReceiptsStack(app, "HsaReceiptArchiverStack", { env });
hsaReceipts.addDependency(platform);

const hsaWeb = new HsaWebStack(app, "HsaWebStack", {
    env,
    userPool: platform.userPool,
    assetsBucket: platform.assetsBucket,
    distribution: platform.distribution,
    dataBucket: hsaReceipts.bucket,
    processorFunction: hsaReceipts.handler,
});
hsaWeb.addDependency(platform);
hsaWeb.addDependency(hsaReceipts);
