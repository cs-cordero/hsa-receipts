// PKCE OAuth 2.0 authentication for HSA Receipts web app.
// Tokens are stored in sessionStorage (cleared when the tab closes).

/**
 * Generate a cryptographically random string for PKCE code_verifier.
 * @param {number} length - Number of random bytes (default 32).
 * @returns {string} URL-safe base64 string.
 */
function generateCodeVerifier(length = 32) {
    const bytes = crypto.getRandomValues(new Uint8Array(length));
    return base64UrlEncode(bytes);
}

/**
 * Compute SHA-256 code_challenge from a code_verifier.
 * @param {string} verifier
 * @returns {Promise<string>} URL-safe base64 hash.
 */
async function generateCodeChallenge(verifier) {
    const encoder = new TextEncoder();
    const data = encoder.encode(verifier);
    const digest = await crypto.subtle.digest("SHA-256", data);
    return base64UrlEncode(new Uint8Array(digest));
}

/**
 * Base64url encode a Uint8Array (no padding).
 * @param {Uint8Array} bytes
 * @returns {string}
 */
function base64UrlEncode(bytes) {
    const binStr = Array.from(bytes, (b) => String.fromCharCode(b)).join("");
    return btoa(binStr).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Generate a random state parameter for CSRF protection.
 * @returns {string}
 */
function generateState() {
    return generateCodeVerifier(16);
}

/**
 * Check whether the current access token is expired or about to expire.
 * @param {number} bufferSeconds - Seconds before actual expiry to consider expired.
 * @returns {boolean}
 */
function isTokenExpired(bufferSeconds = 60) {
    const expiresAt = sessionStorage.getItem("token_expires_at");
    if (!expiresAt) return true;
    return Date.now() >= (parseInt(expiresAt, 10) - bufferSeconds) * 1000;
}

/**
 * Redirect the user to the Cognito hosted UI login page with PKCE.
 */
async function redirectToLogin() {
    const codeVerifier = generateCodeVerifier();
    const codeChallenge = await generateCodeChallenge(codeVerifier);
    const state = generateState();

    sessionStorage.setItem("pkce_code_verifier", codeVerifier);
    sessionStorage.setItem("oauth_state", state);

    const params = new URLSearchParams({
        response_type: "code",
        client_id: CONFIG.clientId,
        redirect_uri: CONFIG.appUrl + CONFIG.callbackPath,
        scope: "openid email",
        state: state,
        code_challenge: codeChallenge,
        code_challenge_method: "S256",
    });

    window.location.href = `${CONFIG.cognitoDomain}/oauth2/authorize?${params}`;
}

/**
 * Exchange an authorization code for tokens using PKCE.
 * Called from callback.html after Cognito redirects back.
 * @returns {Promise<boolean>} true if tokens were obtained successfully.
 */
async function handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const error = params.get("error");

    if (error) {
        console.error("OAuth error:", error, params.get("error_description"));
        return false;
    }

    if (!code || !state) {
        console.error("Missing code or state in callback");
        return false;
    }

    const savedState = sessionStorage.getItem("oauth_state");
    if (state !== savedState) {
        console.error("State mismatch — possible CSRF attack");
        sessionStorage.clear();
        return false;
    }

    const codeVerifier = sessionStorage.getItem("pkce_code_verifier");
    if (!codeVerifier) {
        console.error("Missing PKCE code_verifier");
        return false;
    }

    const tokenUrl = `${CONFIG.cognitoDomain}/oauth2/token`;
    const body = new URLSearchParams({
        grant_type: "authorization_code",
        client_id: CONFIG.clientId,
        code: code,
        redirect_uri: CONFIG.appUrl + CONFIG.callbackPath,
        code_verifier: codeVerifier,
    });

    try {
        const response = await fetch(tokenUrl, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: body,
        });

        if (!response.ok) {
            const text = await response.text();
            console.error("Token exchange failed:", response.status, text);
            return false;
        }

        const tokens = await response.json();
        storeTokens(tokens);

        // Clean up PKCE and state values
        sessionStorage.removeItem("pkce_code_verifier");
        sessionStorage.removeItem("oauth_state");

        return true;
    } catch (err) {
        console.error("Token exchange error:", err);
        return false;
    }
}

/**
 * Store tokens in sessionStorage.
 * @param {{ access_token: string, id_token: string, refresh_token?: string, expires_in: number }} tokens
 */
function storeTokens(tokens) {
    sessionStorage.setItem("access_token", tokens.access_token);
    sessionStorage.setItem("id_token", tokens.id_token);
    if (tokens.refresh_token) {
        sessionStorage.setItem("refresh_token", tokens.refresh_token);
    }
    const expiresAt = Math.floor(Date.now() / 1000) + tokens.expires_in;
    sessionStorage.setItem("token_expires_at", expiresAt.toString());
}

/**
 * Attempt to refresh the access token using the refresh token.
 * @returns {Promise<boolean>} true if refresh succeeded.
 */
async function refreshAccessToken() {
    const refreshToken = sessionStorage.getItem("refresh_token");
    if (!refreshToken) return false;

    const tokenUrl = `${CONFIG.cognitoDomain}/oauth2/token`;
    const body = new URLSearchParams({
        grant_type: "refresh_token",
        client_id: CONFIG.clientId,
        refresh_token: refreshToken,
    });

    try {
        const response = await fetch(tokenUrl, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: body,
        });

        if (!response.ok) return false;

        const tokens = await response.json();
        storeTokens(tokens);
        return true;
    } catch {
        return false;
    }
}

/**
 * Get a valid access token, refreshing if needed.
 * If both access and refresh tokens are expired, redirects to login.
 * @returns {Promise<string>} The access token.
 */
async function getAccessToken() {
    if (!isTokenExpired()) {
        return sessionStorage.getItem("access_token");
    }

    const refreshed = await refreshAccessToken();
    if (refreshed) {
        return sessionStorage.getItem("access_token");
    }

    await redirectToLogin();
    // redirectToLogin navigates away; this line won't execute
    throw new Error("Redirecting to login");
}

/**
 * Initialize auth on page load. If no valid session, redirects to login.
 */
async function initAuth() {
    const accessToken = sessionStorage.getItem("access_token");
    if (!accessToken || isTokenExpired()) {
        const refreshed = await refreshAccessToken();
        if (!refreshed) {
            await redirectToLogin();
            return;
        }
    }
}

/**
 * Sign out — clear tokens and redirect to Cognito logout endpoint.
 */
function signOut() {
    sessionStorage.clear();

    const params = new URLSearchParams({
        client_id: CONFIG.clientId,
        logout_uri: CONFIG.appUrl + CONFIG.logoutPath,
    });

    window.location.href = `${CONFIG.cognitoDomain}/logout?${params}`;
}
