"""Test full OpenCode ACP JSON-RPC flow."""

import asyncio
import json


async def test_full_flow():
    """Test full session/prompt flow."""

    process = await asyncio.create_subprocess_exec(
        "opencode",
        "acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # 1. Initialize
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "capabilities": {},
            "clientInfo": {"name": "nanobot-test", "version": "0.1.0"},
        },
        "id": 1,
    }

    print("1. Initializing...")
    process.stdin.write((json.dumps(init_request) + "\n").encode())
    await process.stdin.drain()

    response = json.loads((await process.stdout.readline()).decode())
    if "error" in response:
        print(f"Initialize failed: {response['error']}")
        return
    print("✓ Initialized")
    print(f"   Result: {json.dumps(response.get('result', {}), indent=2)[:200]}")

    # 2. Create session with required params
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
    print(f"   Response: {json.dumps(session_response, indent=2)}")

    if "error" in session_response:
        print(f"Session creation failed: {session_response['error']}")
        return

    session_id = session_response["result"]["sessionID"]
    print(f"✓ Session created: {session_id}")

    # 3. Send prompt
    prompt_request = {
        "jsonrpc": "2.0",
        "method": "prompt",
        "params": {
            "sessionID": session_id,
            "prompt": "Hello! What model are you running?",
            "directory": "/home/anichols/code/3p/nanobot",
        },
        "id": 3,
    }

    print("\n3. Sending prompt...")
    process.stdin.write((json.dumps(prompt_request) + "\n").encode())
    await process.stdin.drain()

    # 4. Read streaming responses
    print("\n4. Reading streaming responses...")
    chunks = []
    message_count = 0

    try:
        while message_count < 20:  # Limit to avoid infinite loop
            line = await asyncio.wait_for(process.stdout.readline(), timeout=15.0)
            if not line:
                break

            try:
                msg = json.loads(line.decode())
                msg_type = msg.get("type", msg.get("method", "unknown"))

                if "id" in msg:
                    print(f"  Response: {json.dumps(msg, indent=2)[:200]}")
                    if msg.get("result", {}).get("message", {}).get("parts"):
                        for part in msg["result"]["message"]["parts"]:
                            if part.get("type") == "text":
                                text = part.get("content", "")
                                chunks.append(text)
                                print(f"  Text: {text[:100]}...")
                    break
                else:
                    print(f"  Event: {msg_type}")

                message_count += 1
            except json.JSONDecodeError:
                continue

    except asyncio.TimeoutError:
        print("  Timeout waiting for more responses")

    print("\n5. Full response:")
    full_response = "".join(chunks)
    print(full_response[:500] if full_response else "(no text content)")

    # Cleanup
    process.stdin.close()
    await process.wait()


if __name__ == "__main__":
    asyncio.run(test_full_flow())
