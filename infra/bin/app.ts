#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { HsaReceiptArchiverStack } from "../lib/stack";

const app = new cdk.App();
new HsaReceiptArchiverStack(app, "HsaReceiptArchiverStack", {
    env: {
        account: process.env.CDK_DEFAULT_ACCOUNT,
        region: "us-east-1",
    },
});
