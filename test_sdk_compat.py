"""Quick compatibility test: Official ACP SDK with OpenCode."""

import asyncio

from acp.connection import Connection


async def test_sdk_compatibility():
    """Test if official ACP SDK works with OpenCode."""

    print("=== Testing Official ACP SDK with OpenCode ===\n")

    process = None
    connection = None

    # Handler for incoming notifications from agent
    async def handle_agent_method(
        method: str, params: dict | None, is_notification: bool
    ) -> dict | None:
        print(f"   [Agent -> Client] {method}: {str(params)[:100]}...")
        return None  # No response needed for notifications

    try:
        print("1. Spawning OpenCode ACP process...")

        # Spawn subprocess
        process = await asyncio.create_subprocess_exec(
            "opencode",
            "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        print(f"   ✓ Process started (PID: {process.pid})")

        # Create SDK Connection
        print("\n2. Creating ACP Connection...")
        connection = Connection(
            handler=handle_agent_method,
            writer=process.stdin,
            reader=process.stdout,
        )

        print("   ✓ Connection established")

        # 3. Send initialize
        print("\n3. Sending initialize...")
        init_params = {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": "nanobot-test", "version": "0.1.0"},
        }

        init_result = await connection.send_request("initialize", init_params)
        print("   ✓ Initialize succeeded!")
        print(f"   Agent: {init_result.get('agentInfo', {})}")
        print(f"   Protocol version: {init_result.get('protocolVersion')}")

        # 4. Create session
        print("\n4. Creating session...")
        session_params = {
            "cwd": "/home/anichols/code/3p/nanobot",
            "mcpServers": [],
        }

        session_result = await connection.send_request("session/new", session_params)
        print("   ✓ Session created!")
        session_id = session_result.get("sessionId")
        print(f"   Session ID: {session_id}")

        # 5. Send prompt - THE CRITICAL TEST
        print("\n5. Sending prompt via session/prompt...")
        prompt_params = {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": "Say 'OpenCode via ACP SDK works!'"}],
        }

        try:
            # This will wait for the full response
            prompt_result = await asyncio.wait_for(
                connection.send_request("session/prompt", prompt_params), timeout=15.0
            )
            print("   ✓ Prompt completed!")
            print(f"   Stop reason: {prompt_result.get('stopReason')}")
            return True

        except asyncio.TimeoutError:
            print("   ✗ Timeout waiting for prompt response")
            print("   (This suggests OpenCode may not fully implement ACP session/prompt)")
            return False

        except Exception as e:
            print(f"   ✗ session/prompt failed: {e}")
            print("   (OpenCode may not implement standard ACP session/prompt method)")
            return False

    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Cleanup
        if connection:
            try:
                await connection.close()
            except:
                pass
        if process:
            try:
                process.kill()
                await process.wait()
            except:
                pass


if __name__ == "__main__":
    result = asyncio.run(test_sdk_compatibility())
    print(
        f"\n{'SUCCESS - SDK works with OpenCode!' if result else 'FAILED - SDK incompatible or OpenCode non-compliant'}"
    )
