import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as apigatewayv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as apigatewayv2Authorizers from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as apigatewayv2Integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import type { Construct } from "constructs";
import { PYTHON_WEB_BUNDLING_OPTIONS } from "./lambda-bundling";

const SITE_ORIGIN = "https://hsa.corderohq.com";
const API_DOMAIN_NAME = "api.hsa.corderohq.com";

interface HsaWebStackProps extends cdk.StackProps {
    readonly userPool: cognito.IUserPool;
    readonly assetsBucket: s3.IBucket;
    readonly distribution: cloudfront.IDistribution;
    readonly dataBucket: s3.IBucket;
    readonly processorFunction: lambda.IFunction;
    readonly hsaZone: route53.IHostedZone;
    readonly hsaCertificate: acm.ICertificate;
}

export class HsaWebStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props: HsaWebStackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "hsa-web");

        // Cognito User Pool Client for the web app
        const userPoolClient = new cognito.UserPoolClient(this, "WebAppClient", {
            userPool: props.userPool,
            userPoolClientName: "hsa-web-app",
            generateSecret: false,
            preventUserExistenceErrors: true,
            enableTokenRevocation: true,
            authSessionValidity: cdk.Duration.minutes(3),
            idTokenValidity: cdk.Duration.minutes(15),
            accessTokenValidity: cdk.Duration.minutes(15),
            refreshTokenValidity: cdk.Duration.days(1),
            oAuth: {
                flows: { authorizationCodeGrant: true },
                callbackUrls: [`${SITE_ORIGIN}/callback.html`],
                logoutUrls: [`${SITE_ORIGIN}/`],
                scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
            },
        });

        // CloudWatch Log Group
        const logGroup = new logs.LogGroup(this, "WebHandlerLogGroup", {
            logGroupName: "/aws/lambda/hsa-web-handler",
            retention: logs.RetentionDays.ONE_MONTH,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
        });

        // Lambda Function — web API handler
        const webHandler = new lambda.Function(this, "WebHandler", {
            functionName: "hsa-web-handler",
            runtime: lambda.Runtime.PYTHON_3_13,
            handler: "hsa_receipt_archiver.web_handler.handle",
            code: lambda.Code.fromAsset("../lambda", {
                bundling: PYTHON_WEB_BUNDLING_OPTIONS,
            }),
            memorySize: 1024,
            timeout: cdk.Duration.minutes(5),
            logGroup,
            environment: {
                BUCKET_NAME: props.dataBucket.bucketName,
                PROCESSOR_FUNCTION_NAME: props.processorFunction.functionName,
            },
        });

        // IAM Permissions
        props.dataBucket.grantReadWrite(webHandler);
        props.processorFunction.grantInvoke(webHandler);

        // API Gateway HTTP API with Cognito JWT authorizer
        const authorizer = new apigatewayv2Authorizers.HttpUserPoolAuthorizer("CognitoAuthorizer", props.userPool, {
            userPoolClients: [userPoolClient],
        });

        const httpIntegration = new apigatewayv2Integrations.HttpLambdaIntegration("WebHandlerIntegration", webHandler);

        const httpApi = new apigatewayv2.HttpApi(this, "HttpApi", {
            apiName: "hsa-web-api",
            description: "HSA Receipts Web API",
            defaultAuthorizer: authorizer,
            corsPreflight: {
                allowOrigins: [SITE_ORIGIN],
                allowMethods: [
                    apigatewayv2.CorsHttpMethod.GET,
                    apigatewayv2.CorsHttpMethod.PUT,
                    apigatewayv2.CorsHttpMethod.POST,
                    apigatewayv2.CorsHttpMethod.OPTIONS,
                ],
                allowHeaders: ["Authorization", "Content-Type"],
                maxAge: cdk.Duration.hours(1),
            },
        });

        httpApi.addRoutes({
            path: "/ledger",
            methods: [apigatewayv2.HttpMethod.GET],
            integration: httpIntegration,
        });

        httpApi.addRoutes({
            path: "/ledger",
            methods: [apigatewayv2.HttpMethod.PUT],
            integration: httpIntegration,
        });

        httpApi.addRoutes({
            path: "/receipt",
            methods: [apigatewayv2.HttpMethod.POST],
            integration: httpIntegration,
        });

        // API Gateway custom domain — api.hsa.corderohq.com
        const apiDomain = new apigatewayv2.DomainName(this, "ApiDomainName", {
            domainName: API_DOMAIN_NAME,
            certificate: props.hsaCertificate,
        });

        new apigatewayv2.ApiMapping(this, "ApiMapping", {
            api: httpApi,
            domainName: apiDomain,
        });

        new route53.ARecord(this, "ApiDnsRecord", {
            zone: props.hsaZone,
            recordName: API_DOMAIN_NAME,
            target: route53.RecordTarget.fromAlias(
                new route53Targets.ApiGatewayv2DomainProperties(
                    apiDomain.regionalDomainName,
                    apiDomain.regionalHostedZoneId,
                ),
            ),
        });

        // Deploy static web files to the shared assets bucket
        new s3deploy.BucketDeployment(this, "WebAssets", {
            sources: [s3deploy.Source.asset("../web")],
            destinationBucket: props.assetsBucket,
            destinationKeyPrefix: "hsa",
            distribution: props.distribution,
            distributionPaths: ["/*"],
        });

        // Outputs
        new cdk.CfnOutput(this, "SiteUrl", {
            value: SITE_ORIGIN,
            description: "HSA web app URL",
        });

        new cdk.CfnOutput(this, "ApiEndpoint", {
            value: `https://${API_DOMAIN_NAME}`,
            description: "HSA Web API endpoint URL",
        });

        new cdk.CfnOutput(this, "UserPoolClientId", {
            value: userPoolClient.userPoolClientId,
            description: "Cognito User Pool Client ID for the HSA web app",
        });
    }
}
