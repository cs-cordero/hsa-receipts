import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type { Construct } from "constructs";
import type { Stage } from "./constants";

interface PersonalFinanceDynamoDbStackProps extends cdk.StackProps {
    readonly stage: Stage;
}

/**
 * DynamoDB tables for the personal finance app.
 *
 * AWS resources:
 * - DynamoDB table: CategoryGroup-{stage} (PK: groupId)
 * - DynamoDB table: Category-{stage} (PK: categoryId)
 * - DynamoDB table: Budget-{stage} (PK: yearMonth, SK: categoryId)
 * - DynamoDB table: BudgetAuditLog-{stage} (PK: entityType [always "AUDIT"], SK: sortId [ULID])
 * - DynamoDB table: Transactions-{stage} (PK: yearMonth, SK: sortId)
 * - DynamoDB table: Profile-{stage} (PK: householdId [always "HOUSEHOLD"], SK: personId [ULID])
 * - DynamoDB table: Account-{stage} (PK: accountId [ULID])
 * - DynamoDB table: NetWorthSnapshot-{stage} (PK: yearMonth, SK: accountId)
 */
export class PersonalFinanceDynamoDbStack extends cdk.Stack {
    readonly categoryGroupTable: dynamodb.Table;
    readonly categoryTable: dynamodb.Table;
    readonly budgetTable: dynamodb.Table;
    readonly budgetAuditLogTable: dynamodb.Table;
    readonly transactionsTable: dynamodb.Table;
    readonly profileTable: dynamodb.Table;
    readonly accountTable: dynamodb.Table;
    readonly netWorthSnapshotTable: dynamodb.Table;

    constructor(scope: Construct, id: string, props: PersonalFinanceDynamoDbStackProps) {
        super(scope, id, props);

        const { stage } = props;
        // Prod tables are retained on stack delete so an accidental `cdk destroy` (or
        // termination-protection lift) doesn't wipe live data. Dev tables destroy so we
        // can iterate freely. Schema-breaking changes that need table replacement (like
        // the CP3 audit-log PK change) must be handled with a one-shot migration script
        // when they touch prod.
        const removalPolicy = stage === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY;

        cdk.Tags.of(this).add("project", "personal-finance");
        cdk.Tags.of(this).add("stage", stage);

        this.categoryGroupTable = new dynamodb.Table(this, "CategoryGroupTable", {
            tableName: `CategoryGroup-${stage}`,
            partitionKey: { name: "groupId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });

        this.categoryTable = new dynamodb.Table(this, "CategoryTable", {
            tableName: `Category-${stage}`,
            partitionKey: { name: "categoryId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });

        this.budgetTable = new dynamodb.Table(this, "BudgetTable", {
            tableName: `Budget-${stage}`,
            partitionKey: { name: "yearMonth", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "categoryId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });

        this.budgetAuditLogTable = new dynamodb.Table(this, "BudgetAuditLogTable", {
            tableName: `BudgetAuditLog-${stage}`,
            // Single-partition: PK is always the literal "AUDIT", SK is a ULID. Recent-N reads are
            // one Query with ScanIndexForward=false.
            partitionKey: { name: "entityType", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "sortId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });

        this.transactionsTable = new dynamodb.Table(this, "TransactionsTable", {
            tableName: `Transactions-${stage}`,
            partitionKey: { name: "yearMonth", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "sortId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });

        // Net worth tracking (design: net-worth-tracking-design.md §4).
        this.profileTable = new dynamodb.Table(this, "ProfileTable", {
            tableName: `Profile-${stage}`,
            // Item-collection: PK is always "HOUSEHOLD", one item per person (ULID SK).
            // A single Query returns the whole household.
            partitionKey: { name: "householdId", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "personId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });

        this.accountTable = new dynamodb.Table(this, "AccountTable", {
            tableName: `Account-${stage}`,
            partitionKey: { name: "accountId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });

        this.netWorthSnapshotTable = new dynamodb.Table(this, "NetWorthSnapshotTable", {
            tableName: `NetWorthSnapshot-${stage}`,
            partitionKey: { name: "yearMonth", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "accountId", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
            removalPolicy,
        });
    }
}
