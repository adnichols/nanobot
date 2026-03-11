"""Minimal working example of OpenCode ACP JSON-RPC communication.

This demonstrates the correct protocol that nanobot should use.
"""

import asyncio
import json


async def test_working_protocol():
    """Test the working JSON-RPC protocol with OpenCode ACP."""

    # Start opencode acp
    process = await asyncio.create_subprocess_exec(
        "opencode",
        "acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    print("=== Testing Working OpenCode ACP Protocol ===\n")

    try:
        # 1. Send JSON-RPC initialize (method: initialize)
        init_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": 1,  # Must be <= 65535
                "capabilities": {},
                "clientInfo": {"name": "nanobot", "version": "0.1.0"},
            },
            "id": 1,
        }

        print("1. Sending initialize...")
        process.stdin.write((json.dumps(init_request) + "\n").encode())
        await process.stdin.drain()

        response = json.loads((await process.stdout.readline()).decode())
        if "error" in response:
            print(f"   ✗ Failed: {response['error']}")
            return False
        print(f"   ✓ Success! Server: {response['result']['agentInfo']}")

        # 2. Create session (method: session/new with cwd and mcpServers)
        session_request = {
            "jsonrpc": "2.0",
            "method": "session/new",
            "params": {"cwd": "/home/anichols/code/3p/nanobot", "mcpServers": []},
            "id": 2,
        }

        print("\n2. Creating session...")
        process.stdin.write((json.dumps(session_request) + "\n").encode())
        await process.stdin.drain()

        session_response = json.loads((await process.stdout.readline()).decode())
        if "error" in session_response:
            print(f"   ✗ Failed: {session_response['error']}")
            return False

        session_id = session_response["result"]["sessionId"]
        print(f"   ✓ Session: {session_id}")

        # 3. Send prompt (method: ??? - this is what we need to find)
        # Based on SDK, it should be /session/{sessionID}/message
        # In JSON-RPC, this might be "session.message" or similar

        print("\n3. Testing different prompt methods...")

        methods_to_try = [
            "session/message",  # Try hierarchical method name
            "message",  # Try simple method name
            "prompt",  # Try prompt method
            "promptAsync",  # Try promptAsync method
        ]

        for method in methods_to_try:
            prompt_request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": {
                    "sessionID": session_id,
                    "prompt": "Say 'OpenCode working'",  # Simplified prompt
                    "directory": "/home/anichols/code/3p/nanobot",
                },
                "id": 3,
            }

            print(f"\n   Trying method: {method}")
            process.stdin.write((json.dumps(prompt_request) + "\n").encode())
            await process.stdin.drain()

            # Read response with timeout
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)
                if line:
                    response = json.loads(line.decode())
                    if "result" in response:
                        print(f"   ✓ Method {method} WORKS!")
                        print(f"   Response: {json.dumps(response, indent=2)[:400]}")
                        return True
                    elif "error" in response:
                        print(f"   ✗ Method {method} failed: {response['error']['message']}")
            except asyncio.TimeoutError:
                print(f"   ✗ Method {method} timed out")

        print("\n⚠️  None of the methods worked. Need to investigate further.")
        return False

    finally:
        process.stdin.close()
        await process.wait()


if __name__ == "__main__":
    result = asyncio.run(test_working_protocol())
    print(f"\n{'SUCCESS' if result else 'INVESTIGATION NEEDED'}")
