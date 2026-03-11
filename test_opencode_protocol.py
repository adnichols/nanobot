"""Test script to verify OpenCode ACP JSON-RPC protocol.

This script tests the actual communication with opencode acp
to verify the protocol implementation before patching nanobot.
"""

import asyncio
import json
import sys


async def test_opencode_jsonrpc():
    """Test JSON-RPC communication with OpenCode ACP."""

    print("=== Testing OpenCode ACP JSON-RPC Protocol ===\n")

    # Start opencode acp process
    process = await asyncio.create_subprocess_exec(
        "opencode",
        "acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    print(f"Started opencode process (PID: {process.pid})")

    # Send JSON-RPC initialize request
    # Note: Using numeric protocolVersion based on SDK evidence
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": 20241125,  # Numeric as per SDK
            "capabilities": {},
            "clientInfo": {"name": "nanobot-test", "version": "0.1.0"},
        },
        "id": 1,
    }

    print("\nSending initialize request:")
    print(json.dumps(init_request, indent=2))

    init_msg = json.dumps(init_request) + "\n"
    process.stdin.write(init_msg.encode("utf-8"))
    await process.stdin.drain()

    # Read response
    response_line = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)

    if not response_line:
        print("ERROR: No response from opencode")
        return False

    try:
        response = json.loads(response_line.decode("utf-8"))
        print("\nReceived response:")
        print(json.dumps(response, indent=2))

        if "error" in response:
            print(f"\nERROR: {response['error']}")
            return False

        print("\n✓ Initialize succeeded!")

        # Now test creating a session
        session_request = {"jsonrpc": "2.0", "method": "session/new", "params": {}, "id": 2}

        print("\nSending session/new request:")
        print(json.dumps(session_request, indent=2))

        session_msg = json.dumps(session_request) + "\n"
        process.stdin.write(session_msg.encode("utf-8"))
        await process.stdin.drain()

        # Read session response
        session_line = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)

        if session_line:
            session_response = json.loads(session_line.decode("utf-8"))
            print("\nReceived session response:")
            print(json.dumps(session_response, indent=2))

            if "result" in session_response and "sessionID" in session_response.get("result", {}):
                session_id = session_response["result"]["sessionID"]
                print(f"\n✓ Session created: {session_id}")

                # Test sending a prompt
                prompt_request = {
                    "jsonrpc": "2.0",
                    "method": "prompt",
                    "params": {
                        "sessionID": session_id,
                        "prompt": "Hello, what model are you?",
                        "directory": "/home/anichols/code/3p/nanobot",
                    },
                    "id": 3,
                }

                print("\nSending prompt request:")
                print(json.dumps(prompt_request, indent=2))

                prompt_msg = json.dumps(prompt_request) + "\n"
                process.stdin.write(prompt_msg.encode("utf-8"))
                await process.stdin.drain()

                # Read streaming responses
                print("\nReading streaming responses (10 seconds timeout):")
                chunks = []
                try:
                    while True:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
                        if not line:
                            break

                        try:
                            msg = json.loads(line.decode("utf-8"))
                            print(f"  Event: {msg.get('type', msg.get('method', 'unknown'))}")

                            if msg.get("type") == "message.part.delta":
                                delta = msg.get("properties", {}).get("delta", "")
                                chunks.append(delta)
                            elif msg.get("type") == "message.complete":
                                print("\n✓ Message complete")
                                break
                        except json.JSONDecodeError:
                            continue

                except asyncio.TimeoutError:
                    print("\nTimeout waiting for responses")

                full_response = "".join(chunks)
                print("\n=== Full Response ===")
                print(full_response[:500] if full_response else "(no content)")

                return True
            else:
                print("\nERROR: Failed to create session")
                return False
        else:
            print("ERROR: No session response")
            return False

    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON response: {e}")
        return False
    except asyncio.TimeoutError:
        print("ERROR: Timeout waiting for response")
        return False
    finally:
        # Cleanup
        try:
            process.stdin.close()
            await process.wait()
        except:
            pass


if __name__ == "__main__":
    result = asyncio.run(test_opencode_jsonrpc())
    sys.exit(0 if result else 1)
