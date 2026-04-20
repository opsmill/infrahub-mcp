#!/usr/bin/env bash
# Provision Keycloak for the MCP auth e2e tests.
# Idempotent — safe to re-run.
set -euo pipefail

KC_URL="http://localhost:8080"
REALM="infrahub"
CLIENT_ID="infrahub-mcp-client"

# ── helpers ──────────────────────────────────────────────────
kc() {
    # $1 = method, $2 = path (relative to KC_URL), rest = extra curl args
    local method=$1 path=$2; shift 2
    curl -sf -X "$method" "${KC_URL}${path}" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        "$@"
}

kc_ignore409() {
    # Same as kc but treats 409 (conflict / already exists) as success
    local method=$1 path=$2; shift 2
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${KC_URL}${path}" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        "$@")
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ] || [ "$http_code" = "409" ]; then
        return 0
    fi
    echo "  ERROR: $method $path returned HTTP $http_code" >&2
    return 1
}

echo "==> Obtaining admin token"
ADMIN_TOKEN=$(curl -sf -X POST "${KC_URL}/realms/master/protocol/openid-connect/token" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" \
    -d "username=admin" \
    -d "password=admin" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "  OK"

# ── 1. Realm ─────────────────────────────────────────────────
echo "==> Creating realm '${REALM}'"
kc_ignore409 POST "/admin/realms" \
    -d "{\"realm\":\"${REALM}\",\"enabled\":true}"
echo "  OK"

# ── 2. Client scopes ─────────────────────────────────────────
for SCOPE in infrahub:read infrahub:write; do
    echo "==> Creating client scope '${SCOPE}'"
    kc_ignore409 POST "/admin/realms/${REALM}/client-scopes" \
        -d "{
            \"name\":\"${SCOPE}\",
            \"protocol\":\"openid-connect\",
            \"attributes\":{\"include.in.token.scope\":\"true\",\"display.on.consent.screen\":\"true\"}
        }"
    echo "  OK"
done

# ── 3. Client ─────────────────────────────────────────────────
echo "==> Creating client '${CLIENT_ID}'"
kc_ignore409 POST "/admin/realms/${REALM}/clients" \
    -d "{
        \"clientId\":\"${CLIENT_ID}\",
        \"enabled\":true,
        \"publicClient\":true,
        \"directAccessGrantsEnabled\":true,
        \"standardFlowEnabled\":false,
        \"protocol\":\"openid-connect\"
    }"
echo "  OK"

# Get the internal UUID of the client
CLIENT_UUID=$(kc GET "/admin/realms/${REALM}/clients?clientId=${CLIENT_ID}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
echo "  Client UUID: ${CLIENT_UUID}"

# ── 4. Attach scopes to client (optional scopes) ─────────────
for SCOPE in infrahub:read infrahub:write; do
    SCOPE_UUID=$(kc GET "/admin/realms/${REALM}/client-scopes" \
        | python3 -c "import sys,json; scopes=json.load(sys.stdin); print(next(s['id'] for s in scopes if s['name']=='${SCOPE}'))")

    echo "==> Attaching scope '${SCOPE}' (${SCOPE_UUID}) to client as optional"
    # Remove from default if present, then add as optional
    curl -s -o /dev/null -X DELETE "${KC_URL}/admin/realms/${REALM}/clients/${CLIENT_UUID}/default-client-scopes/${SCOPE_UUID}" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" 2>/dev/null || true
    kc_ignore409 PUT "/admin/realms/${REALM}/clients/${CLIENT_UUID}/optional-client-scopes/${SCOPE_UUID}"
    echo "  OK"
done

# ── 5. Add audience mapper to client ─────────────────────────
echo "==> Adding audience protocol mapper"
kc_ignore409 POST "/admin/realms/${REALM}/clients/${CLIENT_UUID}/protocol-mappers/models" \
    -d "{
        \"name\":\"infrahub-mcp-audience\",
        \"protocol\":\"openid-connect\",
        \"protocolMapper\":\"oidc-audience-mapper\",
        \"config\":{
            \"included.custom.audience\":\"infrahub-mcp\",
            \"id.token.claim\":\"false\",
            \"access.token.claim\":\"true\"
        }
    }"
echo "  OK"

# ── 6. Create users with fixed UUIDs ─────────────────────────
create_user() {
    local username=$1 password=$2 email=$3 first=$4 last=$5
    echo "==> Creating user '${username}'"
    kc_ignore409 POST "/admin/realms/${REALM}/users" \
        -d "{
            \"username\":\"${username}\",
            \"email\":\"${email}\",
            \"firstName\":\"${first}\",
            \"lastName\":\"${last}\",
            \"enabled\":true,
            \"emailVerified\":true,
            \"credentials\":[{\"type\":\"password\",\"value\":\"${password}\",\"temporary\":false}]
        }"

    # Get the assigned UUID
    local user_id
    user_id=$(kc GET "/admin/realms/${REALM}/users?username=${username}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
    echo "  UUID: ${user_id}"

    # Ensure password is set (some Keycloak versions ignore inline credentials)
    kc PUT "/admin/realms/${REALM}/users/${user_id}/reset-password" \
        -d "{\"type\":\"password\",\"value\":\"${password}\",\"temporary\":false}" > /dev/null 2>&1 || true
    echo "  OK"
}

create_user "reader-user" "reader-pass" "reader@test.local" "Reader" "User"
create_user "writer-user" "writer-pass" "writer@test.local" "Writer" "User"

# ── 7. Assign default scopes to reader (infrahub:read only) ──
# Keycloak doesn't assign optional client scopes to users directly.
# Instead, the token request decides which optional scopes to include.
# The test script requests specific scopes when getting tokens.
# For reader-user, the test requests only "openid" (default scope).
# For writer-user, the test requests "openid infrahub:read infrahub:write".
#
# However, we need infrahub:read to appear for reader-user even when
# only "openid" is requested. Solution: make infrahub:read a DEFAULT
# client scope so it's always included.

echo "==> Making 'infrahub:read' a default client scope"
READ_SCOPE_UUID=$(kc GET "/admin/realms/${REALM}/client-scopes" \
    | python3 -c "import sys,json; scopes=json.load(sys.stdin); print(next(s['id'] for s in scopes if s['name']=='infrahub:read'))")

# Move infrahub:read from optional to default for this client
curl -s -o /dev/null -X DELETE "${KC_URL}/admin/realms/${REALM}/clients/${CLIENT_UUID}/optional-client-scopes/${READ_SCOPE_UUID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" 2>/dev/null || true
kc_ignore409 PUT "/admin/realms/${REALM}/clients/${CLIENT_UUID}/default-client-scopes/${READ_SCOPE_UUID}"
echo "  OK"

# ── 8. Verify ─────────────────────────────────────────────────
echo ""
echo "==> Verifying OIDC discovery"
OIDC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${KC_URL}/realms/${REALM}/.well-known/openid-configuration")
if [ "$OIDC_STATUS" = "200" ]; then
    echo "  OIDC discovery: OK (HTTP 200)"
else
    echo "  OIDC discovery: FAILED (HTTP ${OIDC_STATUS})"
    exit 1
fi

echo ""
echo "==> Verifying token acquisition"
verify_token() {
    local user=$1 pass=$2 scope=$3
    TOKEN=$(curl -sf -X POST "${KC_URL}/realms/${REALM}/protocol/openid-connect/token" \
        -d "grant_type=password" \
        -d "client_id=${CLIENT_ID}" \
        -d "username=${user}" \
        -d "password=${pass}" \
        -d "scope=${scope}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) || {
        echo "  Token for ${user}: FAILED"
        return 1
    }
    echo "  Token for ${user}: OK"
}

verify_token "reader-user" "reader-pass" "openid"
verify_token "writer-user" "writer-pass" "openid infrahub:read infrahub:write"

echo ""
echo "==> User UUIDs for .env.auth-test credential mapping"
for user in reader-user writer-user; do
    UUID=$(kc GET "/admin/realms/${REALM}/users?username=${user}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
    SAFE=$(echo "$UUID" | tr '[:lower:]-' '[:upper:]_')
    echo "  ${user}: ${UUID}"
    echo "    INFRAHUB_MCP_${SAFE}_API_TOKEN=<infrahub-api-token>"
done

echo ""
echo "Keycloak provisioning complete."
