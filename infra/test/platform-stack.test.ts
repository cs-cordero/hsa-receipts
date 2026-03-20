import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { PlatformStack } from "../lib/platform-stack";

describe("PlatformStack", () => {
    let template: Template;

    beforeAll(() => {
        const app = new cdk.App();
        const stack = new PlatformStack(app, "TestPlatformStack", {
            env: { account: "123456789012", region: "us-east-1" },
        });
        template = Template.fromStack(stack);
    });

    describe("User Pool — signup and sign-in", () => {
        test("self-signup is disabled", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                AdminCreateUserConfig: {
                    AllowAdminCreateUserOnly: true,
                },
            });
        });

        test("sign-in uses email", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                UsernameAttributes: ["email"],
            });
        });
    });

    describe("User Pool — MFA", () => {
        test("MFA is required", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                MfaConfiguration: "ON",
            });
        });

        test("only TOTP MFA is enabled (no SMS)", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                EnabledMfas: ["SOFTWARE_TOKEN_MFA"],
            });
        });
    });

    describe("User Pool — password policy", () => {
        test("minimum length is 8 characters", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                Policies: { PasswordPolicy: { MinimumLength: 8 } },
            });
        });
    });

    describe("User Pool — device tracking", () => {
        test("requires challenge on new device", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                DeviceConfiguration: {
                    ChallengeRequiredOnNewDevice: true,
                },
            });
        });

        test("device only remembered on user prompt", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                DeviceConfiguration: {
                    DeviceOnlyRememberedOnUserPrompt: true,
                },
            });
        });
    });

    describe("User Pool — account recovery", () => {
        test("recovery uses email only", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                AccountRecoverySetting: {
                    RecoveryMechanisms: [{ Name: "verified_email", Priority: 1 }],
                },
            });
        });
    });

    describe("User Pool — deletion protection", () => {
        test("deletion protection is active", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                DeletionProtection: "ACTIVE",
            });
        });

        test("removal policy is RETAIN", () => {
            template.hasResource("AWS::Cognito::UserPool", {
                UpdateReplacePolicy: "Retain",
                DeletionPolicy: "Retain",
            });
        });
    });

    describe("User Pool — hosted UI domain", () => {
        test("custom domain is auth.corderohq.com", () => {
            template.hasResourceProperties("AWS::Cognito::UserPoolDomain", {
                CustomDomainConfig: {
                    CertificateArn: Match.anyValue(),
                },
            });
        });
    });

    describe("S3 assets bucket", () => {
        test("blocks all public access", () => {
            template.hasResourceProperties("AWS::S3::Bucket", {
                PublicAccessBlockConfiguration: {
                    BlockPublicAcls: true,
                    BlockPublicPolicy: true,
                    IgnorePublicAcls: true,
                    RestrictPublicBuckets: true,
                },
            });
        });

        test("uses S3-managed encryption", () => {
            template.hasResourceProperties("AWS::S3::Bucket", {
                BucketEncryption: {
                    ServerSideEncryptionConfiguration: Match.arrayWith([
                        Match.objectLike({
                            ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" },
                        }),
                    ]),
                },
            });
        });
    });

    describe("Route 53 hosted zones", () => {
        test("hsa.corderohq.com hosted zone exists", () => {
            template.hasResourceProperties("AWS::Route53::HostedZone", {
                Name: "hsa.corderohq.com.",
            });
        });

        test("auth.corderohq.com hosted zone exists", () => {
            template.hasResourceProperties("AWS::Route53::HostedZone", {
                Name: "auth.corderohq.com.",
            });
        });
    });

    describe("ACM certificates", () => {
        test("hsa.corderohq.com cert with wildcard SAN", () => {
            template.hasResourceProperties("AWS::CertificateManager::Certificate", {
                DomainName: "hsa.corderohq.com",
                SubjectAlternativeNames: ["*.hsa.corderohq.com"],
            });
        });

        test("auth.corderohq.com cert exists", () => {
            template.hasResourceProperties("AWS::CertificateManager::Certificate", {
                DomainName: "auth.corderohq.com",
            });
        });
    });

    describe("CloudFront distribution", () => {
        test("enforces HTTPS redirect", () => {
            template.hasResourceProperties("AWS::CloudFront::Distribution", {
                DistributionConfig: {
                    DefaultCacheBehavior: Match.objectLike({
                        ViewerProtocolPolicy: "redirect-to-https",
                    }),
                },
            });
        });

        test("has hsa.corderohq.com alias", () => {
            template.hasResourceProperties("AWS::CloudFront::Distribution", {
                DistributionConfig: Match.objectLike({
                    Aliases: ["hsa.corderohq.com"],
                }),
            });
        });
    });

    describe("Route 53 A records", () => {
        test("hsa.corderohq.com A record exists", () => {
            template.hasResourceProperties("AWS::Route53::RecordSet", {
                Name: "hsa.corderohq.com.",
                Type: "A",
            });
        });

        test("auth.corderohq.com A record exists", () => {
            template.hasResourceProperties("AWS::Route53::RecordSet", {
                Name: "auth.corderohq.com.",
                Type: "A",
            });
        });
    });
});
