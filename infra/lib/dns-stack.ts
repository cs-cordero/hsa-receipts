import * as cdk from "aws-cdk-lib";
import * as route53 from "aws-cdk-lib/aws-route53";
import type { Construct } from "constructs";
import { ROOT_DOMAIN } from "./constants";

/**
 * Single hosted zone for every corderohq.com app.
 *
 * Deploys standalone and ahead of every other stack: the root zone must be authoritative in
 * public DNS before any ACM certificate can complete DNS validation against it.
 *
 * AWS resources:
 * - Route 53 hosted zone: corderohq.com (registrar nameservers delegate here)
 * - Route 53 MX record: corderohq.com → null MX (RFC 7505, accepts no mail)
 * - Route 53 TXT record: corderohq.com → SPF hard fail (sends no mail)
 */
export class DnsStack extends cdk.Stack {
    readonly rootZone: route53.HostedZone;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        cdk.Tags.of(this).add("project", "corderohq-platform");

        this.rootZone = new route53.HostedZone(this, "RootZone", {
            zoneName: ROOT_DOMAIN,
        });

        // The apex neither sends nor receives mail. Both records below are scoped to
        // corderohq.com alone — MX and SPF are not inherited by subdomains, so the HSA receipts
        // pipeline is unaffected: it receives at hsa.corderohq.com, which carries its own MX to
        // SES (see HsaReceiptsStack).
        //
        // The null MX (RFC 7505) matters because the apex now has an A record pointing at
        // CloudFront. Without an MX record, senders fall back to delivering at the A record per
        // RFC 5321, so mail to @corderohq.com would be attempted against CloudFront and sit in
        // retry limbo. `MX 0 .` makes it fail immediately and unambiguously instead.
        new route53.MxRecord(this, "ApexNullMx", {
            zone: this.rootZone,
            values: [{ priority: 0, hostName: "." }],
        });

        // Hard fail: no host is authorized to send mail as corderohq.com.
        new route53.TxtRecord(this, "ApexSpf", {
            zone: this.rootZone,
            values: ["v=spf1 -all"],
        });

        new cdk.CfnOutput(this, "RootZoneNameServers", {
            value: cdk.Fn.join(", ", this.rootZone.hostedZoneNameServers ?? []),
            description: "Set these as the nameservers for corderohq.com at the registrar",
        });
    }
}
