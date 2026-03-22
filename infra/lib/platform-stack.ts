import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as s3 from "aws-cdk-lib/aws-s3";
import type { Construct } from "constructs";

export class PlatformStack extends cdk.Stack {
    readonly userPool: cognito.UserPool;
    readonly assetsBucket: s3.Bucket;
    readonly distribution: cloudfront.Distribution;
    readonly hsaZone: route53.HostedZone;
    readonly hsaCertificate: acm.Certificate;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "corderohq-platform");

        // Route 53 hosted zones — delegated from Porkbun via NS records
        this.hsaZone = new route53.HostedZone(this, "HsaZone", {
            zoneName: "hsa.corderohq.com",
        });

        const authZone = new route53.HostedZone(this, "AuthZone", {
            zoneName: "auth.corderohq.com",
        });

        new cdk.CfnOutput(this, "HsaZoneNameServers", {
            value: cdk.Fn.join(", ", this.hsaZone.hostedZoneNameServers ?? []),
            description: "NS records to configure at Porkbun for hsa.corderohq.com",
        });

        new cdk.CfnOutput(this, "AuthZoneNameServers", {
            value: cdk.Fn.join(", ", authZone.hostedZoneNameServers ?? []),
            description: "NS records to configure at Porkbun for auth.corderohq.com",
        });

        // ACM certificates — DNS validated via Route 53
        this.hsaCertificate = new acm.Certificate(this, "HsaCertificate", {
            domainName: "hsa.corderohq.com",
            subjectAlternativeNames: ["*.hsa.corderohq.com"],
            validation: acm.CertificateValidation.fromDns(this.hsaZone),
        });

        const authCertificate = new acm.Certificate(this, "AuthCertificate", {
            domainName: "auth.corderohq.com",
            validation: acm.CertificateValidation.fromDns(authZone),
        });

        // Cognito User Pool — shared authentication for all corderohq.com apps
        this.userPool = new cognito.UserPool(this, "UserPool", {
            userPoolName: "corderohq-users",
            selfSignUpEnabled: false,
            signInAliases: { email: true },
            mfa: cognito.Mfa.REQUIRED,
            mfaSecondFactor: { sms: false, otp: true },
            passwordPolicy: {
                minLength: 8,
                requireLowercase: false,
                requireUppercase: false,
                requireDigits: false,
                requireSymbols: false,
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

        // Cognito custom domain — auth.corderohq.com
        const cognitoDomain = this.userPool.addDomain("CustomDomain", {
            customDomain: {
                domainName: "auth.corderohq.com",
                certificate: authCertificate,
            },
        });

        new route53.ARecord(this, "AuthCognitoAlias", {
            zone: authZone,
            recordName: "auth.corderohq.com",
            target: route53.RecordTarget.fromAlias(new route53Targets.UserPoolDomainTarget(cognitoDomain)),
        });

        // S3 bucket for static web assets — shared across all apps
        // Each app deploys to its own key prefix (e.g., hsa/, budget/)
        this.assetsBucket = new s3.Bucket(this, "AssetsBucket", {
            bucketName: `corderohq-assets-${this.account}-${this.region}`,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

        // CloudFront Function — rewrite directory and extensionless paths
        const urlRewriteCode = [
            "function handler(event) {",
            "    var request = event.request;",
            '    if (request.uri.endsWith("/")) {',
            '        request.uri += "index.html";',
            '    } else if (request.uri.lastIndexOf(".") <= request.uri.lastIndexOf("/")) {',
            '        request.uri += ".html";',
            "    }",
            "    return request;",
            "}",
        ].join("\n");

        const urlRewrite = new cloudfront.Function(this, "IndexRewriteFunction", {
            functionName: "directory-index-rewrite",
            code: cloudfront.FunctionCode.fromInline(urlRewriteCode),
        });

        // CloudFront distribution with OAC to the assets bucket
        this.distribution = new cloudfront.Distribution(this, "Distribution", {
            comment: "corderohq.com web apps",
            defaultBehavior: {
                origin: origins.S3BucketOrigin.withOriginAccessControl(this.assetsBucket, {
                    originPath: "/hsa",
                }),
                viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                functionAssociations: [
                    {
                        function: urlRewrite,
                        eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
                    },
                ],
            },
            defaultRootObject: "index.html",
            priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
            domainNames: ["hsa.corderohq.com"],
            certificate: this.hsaCertificate,
        });

        new route53.ARecord(this, "HsaCloudFrontAlias", {
            zone: this.hsaZone,
            recordName: "hsa.corderohq.com",
            target: route53.RecordTarget.fromAlias(new route53Targets.CloudFrontTarget(this.distribution)),
        });
    }
}
