"""Test OpenCode ACP HTTP API on the correct port."""

import asyncio
import json
import ssl
import urllib.request


async def test_real_acp_api():
    """Test OpenCode ACP HTTP API."""

    # The actual port from the logs
    port = 4096
    base_url = f"http://localhost:{port}"

    print(f"Testing OpenCode ACP on {base_url}")

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Test 1: Check if there's an API endpoint
    api_endpoints = [
        "/api",
        "/api/v1",
        "/api/v2",
        "/mcp",
        "/acp",
        "/jsonrpc",
        "/rpc",
    ]

    print("\n=== Testing API Endpoints ===")
    for endpoint in api_endpoints:
        url = f"{base_url}{endpoint}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, context=ssl_context, timeout=3) as response:
                print(f"  ✓ {endpoint}: {response.status}")
                content = response.read().decode()[:200]
                print(f"    {content}")
        except Exception as e:
            print(f"  ✗ {endpoint}: {type(e).__name__}")

    # Test 2: Try JSON-RPC over HTTP
    print("\n=== Testing JSON-RPC over HTTP ===")
    jsonrpc_endpoints = [
        "/",
        "/jsonrpc",
        "/rpc",
        "/mcp",
    ]

    for endpoint in jsonrpc_endpoints:
        url = f"{base_url}{endpoint}"
        try:
            init_data = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "capabilities": {},
                        "clientInfo": {"name": "nanobot-test", "version": "0.1.0"},
                    },
                    "id": 1,
                }
            ).encode()

            req = urllib.request.Request(
                url, data=init_data, headers={"Content-Type": "application/json"}, method="POST"
            )

            with urllib.request.urlopen(req, context=ssl_context, timeout=5) as response:
                result = json.loads(response.read().decode())
                print(f"  ✓ {endpoint}: JSON-RPC works!")
                print(f"    Response: {json.dumps(result, indent=2)[:300]}")

                # If this worked, try creating a session
                if "result" in result:
                    session_data = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "session/new",
                            "params": {"cwd": "/home/anichols/code/3p/nanobot", "mcpServers": []},
                            "id": 2,
                        }
                    ).encode()

                    req2 = urllib.request.Request(
                        url,
                        data=session_data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )

                    with urllib.request.urlopen(req2, context=ssl_context, timeout=5) as response2:
                        session_result = json.loads(response2.read().decode())
                        print("\n  ✓ Session created!")
                        print(f"    Response: {json.dumps(session_result, indent=2)[:400]}")

                        if "result" in session_result:
                            session_id = session_result["result"]["sessionId"]
                            print(f"\n  Session ID: {session_id}")
                            return True
                break

        except Exception as e:
            print(f"  ✗ {endpoint}: {type(e).__name__}: {e}")

    print("\n=== Testing Session Endpoints ===")
    # Try REST-style endpoints
    session_endpoints = [
        "/session",
        "/api/session",
        "/v2/session",
    ]

    for endpoint in session_endpoints:
        url = f"{base_url}{endpoint}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, context=ssl_context, timeout=3) as response:
                print(f"  ✓ GET {endpoint}: {response.status}")
                content = response.read().decode()[:300]
                print(f"    {content}")
        except Exception as e:
            print(f"  ✗ GET {endpoint}: {type(e).__name__}")

    return False


if __name__ == "__main__":
    result = asyncio.run(test_real_acp_api())
    print(f"\n{'SUCCESS' if result else 'Need more investigation'}")
