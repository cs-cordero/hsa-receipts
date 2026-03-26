import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as s3 from "aws-cdk-lib/aws-s3";
import type { Construct } from "constructs";
import { AUTH_DOMAIN, BUDGET_DOMAIN, HSA_DOMAIN } from "./constants";

/**
 * Shared platform infrastructure for all corderohq.com apps.
 *
 * AWS resources:
 * - Route 53 hosted zone: hsa.corderohq.com (delegated from Porkbun)
 * - Route 53 hosted zone: auth.corderohq.com (delegated from Porkbun)
 * - ACM certificate: hsa.corderohq.com + *.hsa.corderohq.com (DNS validated)
 * - ACM certificate: auth.corderohq.com (DNS validated)
 * - Cognito User Pool: corderohq-users (MFA required, TOTP, no self-signup)
 * - Cognito User Pool Domain: auth.corderohq.com (custom domain)
 * - Route 53 A record: auth.corderohq.com → Cognito
 * - S3 bucket: corderohq-assets (static web assets, shared across apps)
 * - CloudFront Function: directory-index-rewrite (URL rewriting for clean paths)
 * - CloudFront distribution: hsa.corderohq.com → S3 /hsa/ (OAC, HTTPS redirect, /oauth2/* → Cognito proxy)
 * - Route 53 A record: hsa.corderohq.com → CloudFront
 * - Route 53 hosted zone: budget.corderohq.com (delegated from Porkbun)
 * - ACM certificate: budget.corderohq.com + *.budget.corderohq.com (DNS validated)
 */
export class PlatformStack extends cdk.Stack {
    userPool!: cognito.UserPool;
    assetsBucket!: s3.Bucket;
    distribution!: cloudfront.Distribution;
    hsaZone!: route53.HostedZone;
    hsaCertificate!: acm.Certificate;
    budgetZone!: route53.HostedZone;
    budgetCertificate!: acm.Certificate;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "corderohq-platform");

        const authZone = this.createDnsZones();
        const authCertificate = this.createCertificates(authZone);
        this.createBudgetDnsAndCerts();
        const cognitoDomain = this.createCognito(authCertificate);
        this.createCloudFront();
        this.createDnsRecords(authZone, cognitoDomain);
    }

    private createDnsZones(): route53.HostedZone {
        this.hsaZone = new route53.HostedZone(this, "HsaZone", {
            zoneName: HSA_DOMAIN,
        });

        const authZone = new route53.HostedZone(this, "AuthZone", {
            zoneName: AUTH_DOMAIN,
        });

        return authZone;
    }

    private createCertificates(authZone: route53.HostedZone): acm.Certificate {
        this.hsaCertificate = new acm.Certificate(this, "HsaCertificate", {
            domainName: HSA_DOMAIN,
            subjectAlternativeNames: [`*.${HSA_DOMAIN}`],
            validation: acm.CertificateValidation.fromDns(this.hsaZone),
        });

        const authCertificate = new acm.Certificate(this, "AuthCertificate", {
            domainName: AUTH_DOMAIN,
            validation: acm.CertificateValidation.fromDns(authZone),
        });

        return authCertificate;
    }

    private createCognito(authCertificate: acm.Certificate): cognito.UserPoolDomain {
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

        return this.userPool.addDomain("CustomDomain", {
            customDomain: {
                domainName: AUTH_DOMAIN,
                certificate: authCertificate,
            },
        });
    }

    private createCloudFront(): void {
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
            additionalBehaviors: {
                "/oauth2/*": {
                    origin: new origins.HttpOrigin(AUTH_DOMAIN),
                    viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
                    originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
                },
            },
            defaultRootObject: "index.html",
            priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
            domainNames: [HSA_DOMAIN],
            certificate: this.hsaCertificate,
        });
    }

    private createBudgetDnsAndCerts(): void {
        this.budgetZone = new route53.HostedZone(this, "BudgetZone", {
            zoneName: BUDGET_DOMAIN,
        });

        this.budgetCertificate = new acm.Certificate(this, "BudgetCertificate", {
            domainName: BUDGET_DOMAIN,
            subjectAlternativeNames: [`*.${BUDGET_DOMAIN}`],
            validation: acm.CertificateValidation.fromDns(this.budgetZone),
        });
    }

    private createDnsRecords(authZone: route53.HostedZone, cognitoDomain: cognito.UserPoolDomain): void {
        new route53.ARecord(this, "AuthCognitoAlias", {
            zone: authZone,
            recordName: AUTH_DOMAIN,
            target: route53.RecordTarget.fromAlias(new route53Targets.UserPoolDomainTarget(cognitoDomain)),
        });

        new route53.ARecord(this, "HsaCloudFrontAlias", {
            zone: this.hsaZone,
            recordName: HSA_DOMAIN,
            target: route53.RecordTarget.fromAlias(new route53Targets.CloudFrontTarget(this.distribution)),
        });
    }
}
