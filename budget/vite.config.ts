import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function readDevConfig(): { apiOrigin?: string } {
    try {
        return JSON.parse(readFileSync("config.dev.json", "utf-8")) as { apiOrigin?: string };
    } catch {
        return {};
    }
}

const apiOrigin = readDevConfig().apiOrigin;

export default defineConfig({
    plugins: [
        react(),
        {
            // Serves budget/config.dev.json at /config.json during `npm run dev`. The file
            // lives outside public/ so `vite build` never copies it into dist/, which means
            // dev values can't accidentally ship to S3. In prod, CDK's BucketDeployment
            // writes the real config.json via Source.jsonData.
            name: "serve-dev-config",
            configureServer(server) {
                server.middlewares.use("/config.json", (req, res, next) => {
                    if (req.method !== "GET") return next();
                    try {
                        const content = readFileSync("config.dev.json", "utf-8");
                        res.setHeader("Content-Type", "application/json");
                        res.end(content);
                    } catch {
                        res.statusCode = 404;
                        res.setHeader("Content-Type", "text/plain");
                        res.end("config.dev.json not found in budget/");
                    }
                });
            },
        },
    ],
    server: {
        port: 5174,
        proxy: {
            // auth.ts POSTs /oauth2/token and api.ts hits /api/* as relative URLs because
            // CloudFront proxies these to Cognito / API Gateway in prod. Mirror that here so
            // login + API calls work in dev.
            "/oauth2": {
                target: "https://auth.corderohq.com",
                changeOrigin: true,
            },
            ...(apiOrigin && apiOrigin !== "FILL_ME_IN"
                ? {
                      "/api": {
                          target: apiOrigin,
                          changeOrigin: true,
                      },
                  }
                : {}),
        },
    },
});
