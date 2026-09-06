interface AppConfig {
    readonly cognitoDomain: string;
    readonly clientId: string;
    readonly stage: string;
    readonly appUrl: string;
    readonly callbackPath: string;
    readonly logoutPath: string;
}

let _config: AppConfig | null = null;

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null;
}

function requireString(obj: Record<string, unknown>, field: string): string {
    const value = obj[field];
    if (typeof value !== "string") {
        throw new Error(`config.json: '${field}' must be a string, got ${typeof value}`);
    }
    return value;
}

export async function loadConfig(): Promise<AppConfig> {
    if (_config) return _config;

    const resp = await fetch("/config.json");
    if (!resp.ok) {
        throw new Error(`Failed to load config.json: ${resp.status}`);
    }
    const json: unknown = await resp.json();
    if (!isObject(json)) {
        throw new Error("config.json: expected an object");
    }

    _config = Object.freeze({
        cognitoDomain: requireString(json, "cognitoDomain"),
        clientId: requireString(json, "clientId"),
        stage: requireString(json, "stage"),
        appUrl: window.location.origin,
        callbackPath: "/callback",
        logoutPath: "/",
    });
    return _config;
}

export function getConfig(): AppConfig {
    if (!_config) throw new Error("Config not loaded — call loadConfig() first");
    return _config;
}
