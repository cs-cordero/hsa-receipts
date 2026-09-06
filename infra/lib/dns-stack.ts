import * as cdk from "aws-cdk-lib";
import * as route53 from "aws-cdk-lib/aws-route53";
import type { Construct } from "constructs";
import { ROOT_DOMAIN } from "./constants";

/**
 * The single hosted zone for every corderohq.com app.
 *
 * Deploy this stack on its own, and before every other stack. The root zone must be
 * authoritative in public DNS first. Until it is, no ACM certificate can complete its DNS
 * validation.
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

        // The apex sends no mail, and it receives none. Both records below apply to
        // corderohq.com alone. A subdomain does not inherit an MX record or an SPF record, so
        // this does not touch the HSA receipts pipeline. That pipeline receives at
        // hsa.corderohq.com, which has its own MX record to SES. See HsaReceiptsStack.
        //
        // The null MX (RFC 7505) matters, because the apex now has an A record that points at
        // CloudFront. Without an MX record, a sender falls back to the A record, as RFC 5321
        // states. Mail to @corderohq.com would then go to CloudFront, and it would stay in the
        // retry queue. `MX 0 .` makes it fail at once, and for a clear reason.
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
