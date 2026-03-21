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
        test("minimum length is 12 characters", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                Policies: { PasswordPolicy: { MinimumLength: 12 } },
            });
        });

        test("requires lowercase characters", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                Policies: { PasswordPolicy: { RequireLowercase: true } },
            });
        });

        test("requires uppercase characters", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                Policies: { PasswordPolicy: { RequireUppercase: true } },
            });
        });

        test("requires digits", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                Policies: { PasswordPolicy: { RequireNumbers: true } },
            });
        });

        test("requires symbols", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                Policies: { PasswordPolicy: { RequireSymbols: true } },
            });
        });

        test("temporary password expires in 1 day", () => {
            template.hasResourceProperties("AWS::Cognito::UserPool", {
                Policies: { PasswordPolicy: { TemporaryPasswordValidityDays: 1 } },
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
        test("domain prefix is corderohq", () => {
            template.hasResourceProperties("AWS::Cognito::UserPoolDomain", {
                Domain: "corderohq",
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
    });
});
