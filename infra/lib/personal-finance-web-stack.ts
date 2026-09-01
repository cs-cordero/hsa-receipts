import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as apigatewayv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as apigatewayv2Authorizers from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as apigatewayv2Integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import type { Construct } from "constructs";
import type { Stage } from "./constants";
import { AUTH_DOMAIN, personalFinanceDomain, personalFinanceOrigin } from "./constants";

interface PersonalFinanceWebStackProps extends cdk.StackProps {
    readonly stage: Stage;
    readonly userPool: cognito.IUserPool;
    readonly personalFinanceZone: route53.IHostedZone;
    readonly personalFinanceCertificate: acm.ICertificate;
    readonly categoryGroupTable: dynamodb.ITable;
    readonly categoryTable: dynamodb.ITable;
    readonly budgetTable: dynamodb.ITable;
    readonly budgetAuditLogTable: dynamodb.ITable;
    readonly transactionsTable: dynamodb.ITable;
    readonly profileTable: dynamodb.ITable;
    readonly accountTable: dynamodb.ITable;
    readonly netWorthSnapshotTable: dynamodb.ITable;
}

/**
 * Personal finance web app — React frontend served via CloudFront, API via API Gateway.
 *
 * AWS resources:
 * - Cognito User Pool Client: personal-finance-web-app-{stage} (authorization code grant, PKCE)
 * - Cognito User Pool Group: budget-admin-{stage} (admin override authorization for budget feature)
 * - CloudWatch log group: /aws/lambda/personal-finance-handler-{stage}
 * - Lambda function: personal-finance-handler-{stage} (Python 3.13)
 * - IAM policy: DynamoDB read/write on all personal-finance tables (incl. Profile, Account), SSM GetParameter for API key
 * - CloudWatch log group: /aws/lambda/budget-scheduled-densify-{stage}
 * - Lambda function: budget-scheduled-densify-{stage} (Python 3.13, cron-driven)
 * - IAM role: scheduler invoke role for the densify Lambda
 * - EventBridge Schedule: budget-scheduled-densify-{stage} (cron(0 0 1 * ? *) America/New_York)
 * - API Gateway HTTP API: personal-finance-api-{stage} (Cognito JWT authorizer)
 * - API Gateway routes: /api/category-groups (+ /{groupId} rename / deactivate / reorder), /api/categories (+ /{categoryId} GET-preview / PUT / DELETE / reactivate / deactivate / reorder), /api/budget/{yearMonth} (+ /replace, /pin), /api/transactions (+ /upload, /commit, /update, /delete), /api/summary, /api/audit-log, /api/profile (+ /people, /people/{personId} PUT / delete), /api/accounts (+ /reorder, /{accountId} PUT / deactivate / reactivate), /api/net-worth/history, /api/net-worth/{yearMonth} (GET / POST)
 * - S3 bucket: personal-finance-assets-{stage}-{account}-{region} (frontend assets)
 * - CloudFront distribution: S3 origin (frontend) + API Gateway origin (/api/*) + Cognito proxy (/oauth2/*)
 * - Route 53 A record: {stage domain} → CloudFront
 * - S3 BucketDeployment: personal-finance/dist → assets bucket (CloudFront invalidation, config.json injection)
 */
export class PersonalFinanceWebStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props: PersonalFinanceWebStackProps) {
        super(scope, id, props);

        const { stage } = props;

        cdk.Tags.of(this).add("project", "personal-finance");
        cdk.Tags.of(this).add("stage", stage);

        const userPoolClient = this.createUserPoolClient(props.userPool, stage);
        this.createAdminGroup(props.userPool, stage);
        const apiHandler = this.createLambda(props, stage);
        this.createScheduledDensifier(props, stage);
        const httpApi = this.createApiGateway(props, userPoolClient, apiHandler, stage);
        const { distribution, assetsBucket } = this.createCloudFront(httpApi, stage, props.personalFinanceCertificate);
        this.createDnsRecords(props.personalFinanceZone, distribution, stage);
        this.deployFrontend(assetsBucket, distribution, userPoolClient, stage);

        new cdk.CfnOutput(this, "HttpApiUrl", {
            value: httpApi.apiEndpoint,
            description: `Personal finance HTTP API base URL (${stage}) — used as Vite /api proxy target in dev`,
        });
    }

    private createAdminGroup(userPool: cognito.IUserPool, stage: Stage): void {
        new cognito.CfnUserPoolGroup(this, "BudgetAdminGroup", {
            userPoolId: userPool.userPoolId,
            groupName: `budget-admin-${stage}`,
            description: `Budget admins (${stage}). Members can override locked-month rules and perform hard deletes.`,
        });
    }

    private createUserPoolClient(userPool: cognito.IUserPool, stage: Stage): cognito.UserPoolClient {
        const origin = personalFinanceOrigin(stage);
        const callbackUrls = [`${origin}/callback`];
        const logoutUrls = [`${origin}/`];
        if (stage === "dev") {
            callbackUrls.push("http://localhost:5174/callback");
            logoutUrls.push("http://localhost:5174/");
        }

        return new cognito.UserPoolClient(this, "WebAppClient", {
            userPool,
            userPoolClientName: `personal-finance-web-app-${stage}`,
            generateSecret: false,
            preventUserExistenceErrors: true,
            enableTokenRevocation: true,
            authSessionValidity: cdk.Duration.minutes(3),
            idTokenValidity: cdk.Duration.minutes(15),
            accessTokenValidity: cdk.Duration.minutes(15),
            refreshTokenValidity: cdk.Duration.days(1),
            oAuth: {
                flows: { authorizationCodeGrant: true },
                callbackUrls,
                logoutUrls,
                scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
            },
        });
    }

    private createLambda(props: PersonalFinanceWebStackProps, stage: Stage): lambda.Function {
        const logGroup = new logs.LogGroup(this, "ApiHandlerLogGroup", {
            logGroupName: `/aws/lambda/personal-finance-handler-${stage}`,
            retention: logs.RetentionDays.ONE_MONTH,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
        });

        const apiHandler = new lambda.Function(this, "ApiHandler", {
            functionName: `personal-finance-handler-${stage}`,
            runtime: lambda.Runtime.PYTHON_3_13,
            handler: "corderohq.personal_finance_handler.handler",
            code: lambda.Code.fromAsset("../lambda", {
                bundling: {
                    image: lambda.Runtime.PYTHON_3_13.bundlingImage,
                    user: "root",
                    command: [
                        "bash",
                        "-c",
                        [
                            "pip install -r requirements-personal-finance.txt -t /asset-output",
                            "cp -r src/corderohq /asset-output/",
                        ].join(" && "),
                    ],
                },
            }),
            memorySize: 1024,
            timeout: cdk.Duration.minutes(5),
            logGroup,
            environment: {
                CATEGORY_GROUP_TABLE_NAME: props.categoryGroupTable.tableName,
                CATEGORY_TABLE_NAME: props.categoryTable.tableName,
                BUDGET_TABLE_NAME: props.budgetTable.tableName,
                BUDGET_AUDIT_LOG_TABLE_NAME: props.budgetAuditLogTable.tableName,
                TRANSACTIONS_TABLE_NAME: props.transactionsTable.tableName,
                PROFILE_TABLE_NAME: props.profileTable.tableName,
                ACCOUNT_TABLE_NAME: props.accountTable.tableName,
                NETWORTH_SNAPSHOT_TABLE_NAME: props.netWorthSnapshotTable.tableName,
                SSM_API_KEY_PARAM: `/personal-finance/${stage}/anthropic-api-key`,
                STAGE: stage,
            },
        });

        props.categoryGroupTable.grantReadWriteData(apiHandler);
        props.categoryTable.grantReadWriteData(apiHandler);
        props.budgetTable.grantReadWriteData(apiHandler);
        props.budgetAuditLogTable.grantReadWriteData(apiHandler);
        props.transactionsTable.grantReadWriteData(apiHandler);
        props.profileTable.grantReadWriteData(apiHandler);
        props.accountTable.grantReadWriteData(apiHandler);
        props.netWorthSnapshotTable.grantReadWriteData(apiHandler);

        apiHandler.addToRolePolicy(
            new iam.PolicyStatement({
                actions: ["ssm:GetParameter"],
                resources: [
                    cdk.Arn.format(
                        {
                            service: "ssm",
                            resource: "parameter",
                            resourceName: "personal-finance/*",
                        },
                        this,
                    ),
                ],
            }),
        );

        return apiHandler;
    }

    private createScheduledDensifier(props: PersonalFinanceWebStackProps, stage: Stage): void {
        // Dedicated Lambda for the cron path. Reuses the same code package as the
        // API handler (bundled identically) but invokes corderohq.scheduled_densify.handler.
        // Densification doesn't touch transactions or audit, so the IAM scope is narrower.
        const logGroup = new logs.LogGroup(this, "ScheduledDensifyLogGroup", {
            logGroupName: `/aws/lambda/budget-scheduled-densify-${stage}`,
            retention: logs.RetentionDays.ONE_MONTH,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
        });

        const densifyFn = new lambda.Function(this, "ScheduledDensifyHandler", {
            functionName: `budget-scheduled-densify-${stage}`,
            runtime: lambda.Runtime.PYTHON_3_13,
            handler: "corderohq.scheduled_densify.handler",
            code: lambda.Code.fromAsset("../lambda", {
                bundling: {
                    image: lambda.Runtime.PYTHON_3_13.bundlingImage,
                    user: "root",
                    command: [
                        "bash",
                        "-c",
                        [
                            "pip install -r requirements-personal-finance.txt -t /asset-output",
                            "cp -r src/corderohq /asset-output/",
                        ].join(" && "),
                    ],
                },
            }),
            memorySize: 512,
            timeout: cdk.Duration.minutes(5),
            logGroup,
            environment: {
                CATEGORY_TABLE_NAME: props.categoryTable.tableName,
                BUDGET_TABLE_NAME: props.budgetTable.tableName,
                STAGE: stage,
            },
        });

        props.categoryTable.grantReadData(densifyFn);
        props.budgetTable.grantReadWriteData(densifyFn);

        // EventBridge Scheduler needs its own role to invoke the Lambda.
        const schedulerRole = new iam.Role(this, "ScheduledDensifySchedulerRole", {
            assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com"),
        });
        densifyFn.grantInvoke(schedulerRole);

        // Midnight ET on day 1 of every month. ScheduleExpressionTimezone keeps the
        // anchor honest across DST transitions; the architecture spec requires ET.
        new scheduler.CfnSchedule(this, "ScheduledDensifySchedule", {
            name: `budget-scheduled-densify-${stage}`,
            scheduleExpression: "cron(0 0 1 * ? *)",
            scheduleExpressionTimezone: "America/New_York",
            flexibleTimeWindow: { mode: "OFF" },
            target: {
                arn: densifyFn.functionArn,
                roleArn: schedulerRole.roleArn,
            },
            description: `Monthly budget densification trigger (${stage})`,
        });
    }

    private createApiGateway(
        props: PersonalFinanceWebStackProps,
        userPoolClient: cognito.UserPoolClient,
        apiHandler: lambda.Function,
        stage: Stage,
    ): apigatewayv2.HttpApi {
        const authorizer = new apigatewayv2Authorizers.HttpUserPoolAuthorizer("CognitoAuthorizer", props.userPool, {
            userPoolClients: [userPoolClient],
        });

        const integration = new apigatewayv2Integrations.HttpLambdaIntegration("ApiHandlerIntegration", apiHandler);

        const httpApi = new apigatewayv2.HttpApi(this, "HttpApi", {
            apiName: `personal-finance-api-${stage}`,
            description: `Personal finance API (${stage})`,
            defaultAuthorizer: authorizer,
        });

        // Every API Gateway v2 HTTP API path must be declared explicitly — there's no
        // catch-all behavior. If a path isn't here, API Gateway returns 404 before the
        // Lambda dispatcher ever sees the request. Keep this list in lockstep with the
        // routes branched on in personal_finance_handler.handler.
        const routes: { path: string; methods: apigatewayv2.HttpMethod[] }[] = [
            // Category groups (CP12)
            { path: "/api/category-groups", methods: [apigatewayv2.HttpMethod.GET, apigatewayv2.HttpMethod.POST] },
            {
                path: "/api/category-groups/{groupId}",
                methods: [apigatewayv2.HttpMethod.PUT, apigatewayv2.HttpMethod.DELETE],
            },
            { path: "/api/category-groups/reorder", methods: [apigatewayv2.HttpMethod.POST] },

            // Categories
            { path: "/api/categories", methods: [apigatewayv2.HttpMethod.GET, apigatewayv2.HttpMethod.POST] },
            { path: "/api/categories/reorder", methods: [apigatewayv2.HttpMethod.POST] },
            {
                path: "/api/categories/{categoryId}",
                methods: [
                    apigatewayv2.HttpMethod.GET, // CP9 deletion preview (?deletion_preview=true)
                    apigatewayv2.HttpMethod.PUT,
                    apigatewayv2.HttpMethod.DELETE, // CP9 hard delete
                ],
            },
            { path: "/api/categories/{categoryId}/reactivate", methods: [apigatewayv2.HttpMethod.POST] },
            { path: "/api/categories/{categoryId}/deactivate", methods: [apigatewayv2.HttpMethod.POST] }, // CP8

            // Budget
            { path: "/api/budget/{yearMonth}", methods: [apigatewayv2.HttpMethod.GET] },
            { path: "/api/budget/{yearMonth}/replace", methods: [apigatewayv2.HttpMethod.POST] }, // CP4
            { path: "/api/budget/{yearMonth}/pin", methods: [apigatewayv2.HttpMethod.POST] }, // CP6

            // Transactions
            { path: "/api/transactions", methods: [apigatewayv2.HttpMethod.GET, apigatewayv2.HttpMethod.POST] },
            { path: "/api/transactions/upload", methods: [apigatewayv2.HttpMethod.POST] },
            { path: "/api/transactions/commit", methods: [apigatewayv2.HttpMethod.POST] }, // CP10
            { path: "/api/transactions/update", methods: [apigatewayv2.HttpMethod.POST] },
            { path: "/api/transactions/delete", methods: [apigatewayv2.HttpMethod.POST] },

            // Read endpoints
            { path: "/api/summary", methods: [apigatewayv2.HttpMethod.GET] },
            { path: "/api/audit-log", methods: [apigatewayv2.HttpMethod.GET] },

            // Household profile (net worth)
            { path: "/api/profile", methods: [apigatewayv2.HttpMethod.GET] },
            { path: "/api/profile/people", methods: [apigatewayv2.HttpMethod.POST] },
            { path: "/api/profile/people/{personId}", methods: [apigatewayv2.HttpMethod.PUT] },
            { path: "/api/profile/people/{personId}/delete", methods: [apigatewayv2.HttpMethod.POST] },

            // Accounts (net worth)
            { path: "/api/accounts", methods: [apigatewayv2.HttpMethod.GET, apigatewayv2.HttpMethod.POST] },
            { path: "/api/accounts/reorder", methods: [apigatewayv2.HttpMethod.POST] },
            { path: "/api/accounts/{accountId}", methods: [apigatewayv2.HttpMethod.PUT] },
            { path: "/api/accounts/{accountId}/deactivate", methods: [apigatewayv2.HttpMethod.POST] },
            { path: "/api/accounts/{accountId}/reactivate", methods: [apigatewayv2.HttpMethod.POST] },

            // Net worth snapshots. The static /history route sits alongside the
            // /{yearMonth} param route — HTTP API matches the exact segment first.
            { path: "/api/net-worth/history", methods: [apigatewayv2.HttpMethod.GET] },
            {
                path: "/api/net-worth/{yearMonth}",
                methods: [apigatewayv2.HttpMethod.GET, apigatewayv2.HttpMethod.POST],
            },
        ];

        for (const route of routes) {
            httpApi.addRoutes({
                path: route.path,
                methods: route.methods,
                integration,
            });
        }

        return httpApi;
    }

    private createCloudFront(
        httpApi: apigatewayv2.HttpApi,
        stage: Stage,
        personalFinanceCertificate: acm.ICertificate,
    ): { distribution: cloudfront.Distribution; assetsBucket: s3.Bucket } {
        const domain = personalFinanceDomain(stage);

        // The assets bucket only holds the built React frontend + config.json — everything
        // in it is reproducible from `npm run build` + a redeploy, so DESTROY in both
        // stages. No RETAIN gymnastics needed on stack destroy.
        const assetsBucket = new s3.Bucket(this, "AssetsBucket", {
            bucketName: `personal-finance-assets-${stage}-${this.account}-${this.region}`,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
            autoDeleteObjects: true,
        });

        // Origin request policy for API Gateway — forward all viewer headers (including Authorization)
        const apiOriginRequestPolicy = cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER;

        const apiOriginDomain = `${httpApi.httpApiId}.execute-api.${this.region}.amazonaws.com`;

        const distribution = new cloudfront.Distribution(this, "Distribution", {
            comment: `Personal finance app (${stage})`,
            defaultBehavior: {
                origin: origins.S3BucketOrigin.withOriginAccessControl(assetsBucket),
                viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cachePolicy: stage === "dev" ? cloudfront.CachePolicy.CACHING_DISABLED : undefined,
            },
            additionalBehaviors: {
                "/api/*": {
                    origin: new origins.HttpOrigin(apiOriginDomain),
                    viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
                    originRequestPolicy: apiOriginRequestPolicy,
                    allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
                },
                "/oauth2/*": {
                    origin: new origins.HttpOrigin(AUTH_DOMAIN),
                    viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
                    originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
                },
            },
            defaultRootObject: "index.html",
            errorResponses: [
                {
                    httpStatus: 403,
                    responseHttpStatus: 200,
                    responsePagePath: "/index.html",
                },
                {
                    httpStatus: 404,
                    responseHttpStatus: 200,
                    responsePagePath: "/index.html",
                },
            ],
            priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
            domainNames: [domain],
            certificate: personalFinanceCertificate,
        });

        return { distribution, assetsBucket };
    }

    private deployFrontend(
        assetsBucket: s3.Bucket,
        distribution: cloudfront.Distribution,
        userPoolClient: cognito.UserPoolClient,
        stage: Stage,
    ): void {
        new s3deploy.BucketDeployment(this, "FrontendDeployment", {
            sources: [
                s3deploy.Source.asset("../personal-finance/dist"),
                s3deploy.Source.jsonData("config.json", {
                    cognitoDomain: "https://auth.corderohq.com",
                    clientId: userPoolClient.userPoolClientId,
                    stage,
                }),
            ],
            destinationBucket: assetsBucket,
            ...(stage === "prod" ? { distribution, distributionPaths: ["/*"] } : {}),
        });

        new cdk.CfnOutput(this, "UserPoolClientId", {
            value: userPoolClient.userPoolClientId,
            description: `Personal finance app Cognito client ID (${stage})`,
        });
    }

    private createDnsRecords(
        personalFinanceZone: route53.IHostedZone,
        distribution: cloudfront.Distribution,
        stage: Stage,
    ): void {
        const domain = personalFinanceDomain(stage);

        new route53.ARecord(this, "CloudFrontAlias", {
            zone: personalFinanceZone,
            recordName: domain,
            target: route53.RecordTarget.fromAlias(new route53Targets.CloudFrontTarget(distribution)),
        });
    }
}
