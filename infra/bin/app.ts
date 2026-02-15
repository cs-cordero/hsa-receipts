#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { HsaReceiptsStack } from "../lib/stack.js";

const app = new cdk.App();
new HsaReceiptsStack(app, "HsaReceiptsStack", {
    env: {
        account: process.env.CDK_DEFAULT_ACCOUNT,
        region: "us-east-1",
    },
});
