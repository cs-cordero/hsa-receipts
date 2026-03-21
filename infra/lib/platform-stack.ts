import * as cdk from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as s3 from "aws-cdk-lib/aws-s3";
import type { Construct } from "constructs";

export class PlatformStack extends cdk.Stack {
    readonly userPool: cognito.UserPool;
    readonly assetsBucket: s3.Bucket;
    readonly distribution: cloudfront.Distribution;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "corderohq-platform");

        // Cognito User Pool — shared authentication for all corderohq.com apps
        this.userPool = new cognito.UserPool(this, "UserPool", {
            userPoolName: "corderohq-users",
            selfSignUpEnabled: false,
            signInAliases: { email: true },
            mfa: cognito.Mfa.REQUIRED,
            mfaSecondFactor: { sms: false, otp: true },
            passwordPolicy: {
                minLength: 12,
                requireLowercase: true,
                requireUppercase: true,
                requireDigits: true,
                requireSymbols: true,
                tempPasswordValidity: cdk.Duration.days(1),
            },
            deviceTracking: {
                challengeRequiredOnNewDevice: true,
                deviceOnlyRememberedOnUserPrompt: true,
            },
            accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
            removalPolicy: cdk.RemovalPolicy.RETAIN,
            deletionProtection: true,
        });

        // Cognito Hosted UI domain
        this.userPool.addDomain("Domain", {
            cognitoDomain: { domainPrefix: "corderohq" },
        });

        // S3 bucket for static web assets — shared across all apps
        // Each app deploys to its own key prefix (e.g., hsa/, budget/)
        this.assetsBucket = new s3.Bucket(this, "AssetsBucket", {
            bucketName: `corderohq-assets-${this.account}-${this.region}`,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

        // CloudFront distribution with OAC to the assets bucket
        this.distribution = new cloudfront.Distribution(this, "Distribution", {
            comment: "corderohq.com web apps",
            defaultBehavior: {
                origin: origins.S3BucketOrigin.withOriginAccessControl(this.assetsBucket),
                viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            },
            defaultRootObject: "index.html",
            priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
        });
    }
}
