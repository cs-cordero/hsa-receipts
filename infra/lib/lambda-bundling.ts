import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";

export const PYTHON_BUNDLING_OPTIONS: cdk.BundlingOptions = {
    image: lambda.Runtime.PYTHON_3_13.bundlingImage,
    user: "root",
    command: [
        "bash",
        "-c",
        [
            "dnf install -y ghostscript",
            "pip install -r requirements.txt -t /asset-output",
            "cp -r src/hsa_receipt_archiver /asset-output/",
            "mkdir -p /asset-output/bin /asset-output/lib",
            "cp /usr/bin/gs /asset-output/bin/gs",
            "ldd /usr/bin/gs | awk '/=>/ {print $3}' | xargs -I{} cp {} /asset-output/lib/",
            "cp -rL /usr/share/ghostscript /asset-output/share/",
        ].join(" && "),
    ],
};

export const PYTHON_WEB_BUNDLING_OPTIONS: cdk.BundlingOptions = {
    image: lambda.Runtime.PYTHON_3_13.bundlingImage,
    user: "root",
    command: [
        "bash",
        "-c",
        ["pip install -r requirements-web.txt -t /asset-output", "cp -r src/hsa_receipt_archiver /asset-output/"].join(
            " && ",
        ),
    ],
};
