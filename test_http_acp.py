"""Test OpenCode ACP HTTP server with better debugging."""

import asyncio
import ssl
import urllib.request


async def test_http_acp():
    """Test OpenCode ACP HTTP server on fixed port."""

    port = 18791

    # Start opencode acp with fixed port and capture stderr
    process = await asyncio.create_subprocess_exec(
        "opencode",
        "acp",
        "--port",
        str(port),
        "--print-logs",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    print(f"Starting opencode acp on port {port}...")

    # Read stderr to see what's happening
    async def read_stderr():
        while True:
            try:
                line = await asyncio.wait_for(process.stderr.readline(), timeout=0.5)
                if line:
                    line_str = line.decode().strip()
                    if (
                        "server" in line_str.lower()
                        or "port" in line_str.lower()
                        or "listen" in line_str.lower()
                    ):
                        print(f"  [stderr] {line_str[:120]}")
            except asyncio.TimeoutError:
                break

    # Wait for server to be ready
    print("\nWaiting for server to start (reading stderr)...")
    await read_stderr()

    print("\nWaiting 5 more seconds...")
    await asyncio.sleep(5)

    await read_stderr()

    print(f"\nOpenCode ACP should be on http://localhost:{port}")

    # Try to communicate via HTTP
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Try different endpoints
    endpoints = [
        f"http://localhost:{port}/",
        f"http://localhost:{port}/health",
        f"http://127.0.0.1:{port}/",
    ]

    for endpoint in endpoints:
        try:
            print(f"\nTrying {endpoint}")
            req = urllib.request.Request(endpoint, method="GET")
            with urllib.request.urlopen(req, context=ssl_context, timeout=5) as response:
                result = response.read().decode()
                print(f"  ✓ Response: {result[:400]}")
                break
        except Exception as e:
            print(f"  ✗ {type(e).__name__}: {e}")

    # Cleanup
    print("\nCleaning up...")
    process.kill()
    await process.wait()
    print("Done")


if __name__ == "__main__":
    asyncio.run(test_http_acp())
