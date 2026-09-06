import * as cdk from "aws-cdk-lib";
import type * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import type { Construct } from "constructs";
import { MATH_DOMAIN } from "./constants";

interface MathQuizStackProps extends cdk.StackProps {
    readonly rootZone: route53.IHostedZone;
    readonly certificate: acm.ICertificate;
}

/**
 * Math quiz — a single static page, with no API and no sign-in.
 *
 * The page keeps high scores and the player name in localStorage, and it makes no network
 * call. So this stack needs a bucket and a distribution, and nothing else.
 *
 * This stack owns its bucket instead of using the shared assets bucket in PlatformStack.
 * Origin access control writes the distribution ARN into the bucket policy, so a shared
 * bucket would make PlatformStack depend on this stack while this stack depends on it.
 * The personal finance stacks own their buckets for the same reason.
 *
 * AWS resources:
 * - S3 bucket: math-quiz-assets-{account}-{region} (the game page)
 * - CloudFront distribution: math.corderohq.com → S3 (OAC, HTTPS redirect)
 * - Route 53 A record: math.corderohq.com → CloudFront
 * - S3 BucketDeployment: math/ → the bucket (CloudFront invalidation)
 */
export class MathQuizStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props: MathQuizStackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "math-quiz");

        // Everything here is rebuilt from math/ on each deploy, so DESTROY is safe.
        const assetsBucket = new s3.Bucket(this, "AssetsBucket", {
            bucketName: `math-quiz-assets-${this.account}-${this.region}`,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
            autoDeleteObjects: true,
        });

        const distribution = new cloudfront.Distribution(this, "Distribution", {
            comment: "math.corderohq.com",
            defaultBehavior: {
                origin: origins.S3BucketOrigin.withOriginAccessControl(assetsBucket),
                viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            },
            defaultRootObject: "index.html",
            // The game is one page, so send every other path back to it.
            errorResponses: [
                { httpStatus: 403, responseHttpStatus: 200, responsePagePath: "/index.html" },
                { httpStatus: 404, responseHttpStatus: 200, responsePagePath: "/index.html" },
            ],
            priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
            // math.corderohq.com is already covered by the *.corderohq.com name on the shared
            // certificate, so this subdomain needs no certificate work.
            domainNames: [MATH_DOMAIN],
            certificate: props.certificate,
        });

        new route53.ARecord(this, "MathCloudFrontAlias", {
            zone: props.rootZone,
            recordName: MATH_DOMAIN,
            target: route53.RecordTarget.fromAlias(new route53Targets.CloudFrontTarget(distribution)),
        });

        new s3deploy.BucketDeployment(this, "MathAssets", {
            // `followSymlinks: EXTERNAL` resolves favicon.svg, which points at ../shared/.
            sources: [
                s3deploy.Source.asset("../math", {
                    followSymlinks: cdk.SymlinkFollowMode.EXTERNAL,
                }),
            ],
            destinationBucket: assetsBucket,
            distribution,
            distributionPaths: ["/*"],
        });
    }
}
