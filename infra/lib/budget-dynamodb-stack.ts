import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type { Construct } from "constructs";
import type { Stage } from "./constants";

interface BudgetDynamoDbStackProps extends cdk.StackProps {
    readonly stage: Stage;
}

/**
 * DynamoDB tables for the budget app.
 *
 * AWS resources:
 * - DynamoDB table: CategoryGroup-{stage} (PK: groupId)
 * - DynamoDB table: Category-{stage} (PK: categoryId)
 * - DynamoDB table: Budget-{stage} (PK: yearMonth, SK: categoryId)
 * - DynamoDB table: BudgetAuditLog-{stage} (PK: entityType [always "AUDIT"], SK: sortId [ULID])
 * - DynamoDB table: Transactions-{stage} (PK: yearMonth, SK: sortId)
 */
export class BudgetDynamoDbStack extends cdk.Stack {
    readonly categoryGroupTable: dynamodb.Table;
    readonly categoryTable: dynamodb.Table;
    readonly budgetTable: dynamodb.Table;
    readonly budgetAuditLogTable: dynamodb.Table;
    readonly transactionsTable: dynamodb.Table;

    constructor(scope: Construct, id: string, props: BudgetDynamoDbStackProps) {
        super(scope, id, props);

        const { stage } = props;
        // Flipped prod to DESTROY for the CP3 audit-log schema replacement (PK change forces
        // table replacement, which requires CFN to be able to delete the old table). No data
        // of value in either stage yet. Revisit once prod actually holds audit entries worth
        // preserving — at that point a one-shot migration script + RETAIN is the right move.
        const removalPolicy = cdk.RemovalPolicy.DESTROY;

        cdk.Tags.of(this).add("project", "budget");
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
    }
}
