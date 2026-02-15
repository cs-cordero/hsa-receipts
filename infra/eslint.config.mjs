import eslint from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";
import eslintPluginPrettier from "eslint-plugin-prettier/recommended";

export default defineConfig(
    eslint.configs.recommended,
    ...tseslint.configs.strictTypeChecked,
    ...tseslint.configs.stylisticTypeChecked,
    eslintPluginPrettier,
    {
        languageOptions: {
            parserOptions: {
                projectService: {
                    allowDefaultProject: ["*.mjs"],
                },
                tsconfigRootDir: import.meta.dirname,
            },
        },
    },
    {
        ignores: ["dist/", "cdk.out/", "node_modules/", "*.js", "*.d.ts"],
    },
);
