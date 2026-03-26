/**
 * Small set of runtime validation primitives.
 *
 * Goal: turn `unknown` (e.g. JSON parsed from an API response) into typed values
 * with real runtime checks. No `as` casts — every narrowing is done by a type
 * predicate so TypeScript's narrowing does the work.
 *
 * All `require*` helpers throw on mismatch; `optional*` helpers return undefined
 * when the field is missing (`undefined` or absent) and throw on wrong type.
 */

export function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function describe(value: unknown): string {
    if (value === null) return "null";
    if (Array.isArray(value)) return "array";
    return typeof value;
}

function path(parentLabel: string, field: string): string {
    return parentLabel ? `${parentLabel}.${field}` : field;
}

export function requireObject(value: unknown, label: string): Record<string, unknown> {
    if (!isObject(value)) {
        throw new Error(`${label} must be an object, got ${describe(value)}`);
    }
    return value;
}

export function requireArray(value: unknown, label: string): unknown[] {
    if (!Array.isArray(value)) {
        throw new Error(`${label} must be an array, got ${describe(value)}`);
    }
    return value;
}

export function requireString(obj: Record<string, unknown>, field: string, parentLabel = ""): string {
    const value = obj[field];
    if (typeof value !== "string") {
        throw new Error(`${path(parentLabel, field)} must be a string, got ${describe(value)}`);
    }
    return value;
}

export function requireNumber(obj: Record<string, unknown>, field: string, parentLabel = ""): number {
    const value = obj[field];
    if (typeof value !== "number") {
        throw new Error(`${path(parentLabel, field)} must be a number, got ${describe(value)}`);
    }
    return value;
}

export function requireBoolean(obj: Record<string, unknown>, field: string, parentLabel = ""): boolean {
    const value = obj[field];
    if (typeof value !== "boolean") {
        throw new Error(`${path(parentLabel, field)} must be a boolean, got ${describe(value)}`);
    }
    return value;
}

export function optionalString(obj: Record<string, unknown>, field: string, parentLabel = ""): string | undefined {
    const value = obj[field];
    if (value === undefined) return undefined;
    if (typeof value !== "string") {
        throw new Error(`${path(parentLabel, field)} must be a string or absent, got ${describe(value)}`);
    }
    return value;
}

export function optionalNumber(obj: Record<string, unknown>, field: string, parentLabel = ""): number | undefined {
    const value = obj[field];
    if (value === undefined) return undefined;
    if (typeof value !== "number") {
        throw new Error(`${path(parentLabel, field)} must be a number or absent, got ${describe(value)}`);
    }
    return value;
}

export function optionalBoolean(obj: Record<string, unknown>, field: string, parentLabel = ""): boolean | undefined {
    const value = obj[field];
    if (value === undefined) return undefined;
    if (typeof value !== "boolean") {
        throw new Error(`${path(parentLabel, field)} must be a boolean or absent, got ${describe(value)}`);
    }
    return value;
}

export function arrayOf<T>(value: unknown, parseItem: (item: unknown, index: number) => T, label: string): T[] {
    return requireArray(value, label).map(parseItem);
}

export function stringArray(value: unknown, label: string): string[] {
    return arrayOf(
        value,
        (item, index) => {
            if (typeof item !== "string") {
                throw new Error(`${label}[${index}] must be a string, got ${describe(item)}`);
            }
            return item;
        },
        label,
    );
}
