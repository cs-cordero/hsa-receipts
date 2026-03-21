// Configuration for HSA Receipts web app.
// Update these values after running `cdk deploy`.
const CONFIG = Object.freeze({
    // Cognito hosted UI domain (e.g., "https://corderohq.auth.us-east-1.amazoncognito.com")
    cognitoDomain: "https://corderohq.auth.us-east-1.amazoncognito.com",

    // Cognito User Pool Client ID (from HsaWebStack output: UserPoolClientId)
    clientId: "PLACEHOLDER_CLIENT_ID",

    // CloudFront distribution URL (no trailing slash)
    appUrl: "https://PLACEHOLDER.cloudfront.net",

    // API Gateway endpoint (from HsaWebStack output: ApiEndpoint)
    apiEndpoint: "https://PLACEHOLDER.execute-api.us-east-1.amazonaws.com",

    // OAuth redirect paths
    callbackPath: "/hsa/callback.html",
    logoutPath: "/hsa/",
});
