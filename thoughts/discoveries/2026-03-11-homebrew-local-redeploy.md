# Homebrew Local Redeploy Notes

Date: 2026-03-11

## Goal

Capture the working local-only Homebrew redeploy path for installing the current `nanobot` repo checkout onto this machine without publishing anything publicly.

## What was true on this machine

- The active Homebrew service was running `nanobot gateway` from Homebrew.
- `brew info nanobot` initially referred to the Homebrew Core formula, not the local repo formula.
- The repo's checked-in `Formula/nanobot.rb` installs from a fixed PyPI tarball, so a plain `brew reinstall nanobot` would not pick up uncommitted or unreleased local repo changes.
- Homebrew rejected a raw local formula path with:
  - `Homebrew requires formulae to be in a tap`
- Shell PATH did not point at the Homebrew binary:
  - `which nanobot` -> `/home/anichols/.local/bin/nanobot`
- The Homebrew service did point at the Homebrew binary:
  - `/home/linuxbrew/.linuxbrew/opt/nanobot/bin/nanobot gateway`

## Working local-only redeploy flow

This does not publish anything. It uses a local tarball and a local tap on the same machine.

### 1. Build a tarball from the current repo checkout

From repo root:

```bash
tar --exclude=.git -czf /tmp/nanobot-local-src.tar.gz .
```

### 2. Generate a local formula that points at that tarball

Starting from the repo's `Formula/nanobot.rb`, replace:
- `url` with `file:///tmp/nanobot-local-src.tar.gz`
- `sha256` with the tarball sha256
- add/update `version` to the repo version being deployed

On this run the generated local formula was written to:
- `/tmp/nanobot-local.rb`

### 3. Create or reuse a local-only tap

```bash
brew tap-new anichols/local
```

Tap path on this machine:
- `/home/linuxbrew/.linuxbrew/Homebrew/Library/Taps/anichols/homebrew-local`

### 4. Copy the generated formula into the local tap

Target path:
- `/home/linuxbrew/.linuxbrew/Homebrew/Library/Taps/anichols/homebrew-local/Formula/nanobot.rb`

### 5. Reinstall from the local tap

```bash
HOMEBREW_NO_INSTALL_FROM_API=1 brew reinstall --build-from-source anichols/local/nanobot
```

## Warning seen during reinstall

Homebrew printed:

```text
Warning: building from source is not supported!
You're on your own. Failures are expected so don't create any issues, please!
```

### Meaning

This is a Homebrew policy warning for unsupported source builds from a local/custom formula path or tap. It does not mean the build is broken. It means Homebrew will not treat this local-source build path as a supported end-user distribution channel.

### How to make the warning go away

You generally do not remove it for a local repo deploy. To avoid the warning, use one of these supported paths instead:
- install a bottled formula from Homebrew Core or another supported tap
- publish and bottle the formula in a proper tap/CI workflow
- avoid Homebrew entirely for local dev installs

For local repo deployment on a single machine, treat the warning as expected.

## Restart command

```bash
brew services restart anichols/local/nanobot
```

Observed result on this machine:
- service label: `homebrew.nanobot`
- service status: `started`

## Verification used

### Confirm the installed formula source

```bash
brew info anichols/local/nanobot
```

Expected indicators:
- `From: /home/linuxbrew/.linuxbrew/Homebrew/Library/Taps/anichols/homebrew-local/Formula/nanobot.rb`
- built from source timestamp matching the redeploy

### Confirm the service process is using the Homebrew binary

```bash
ps -eo pid,cmd | grep '/opt/nanobot/bin/nanobot gateway' | grep -v grep
```

### Confirm the installed Homebrew package contains the change

Search inside the cellar package, for example for the ACP fallback toggle:

```bash
grep -R "allow_local_fallback\|acp_allow_local_fallback" /home/linuxbrew/.linuxbrew/Cellar/nanobot/0.1.4.post5
```

### Smoke test the Homebrew-managed binary directly

Use the explicit Homebrew binary, not `which nanobot`, because shell PATH may resolve to `~/.local/bin/nanobot`:

```bash
/home/linuxbrew/.linuxbrew/opt/nanobot/bin/nanobot agent --logs -m "Say exactly 'BREW ACP OK' and nothing else"
```

Observed result on this machine:
- ACP session log line appeared
- final output was `BREW ACP OK`

## Important gotcha

There are two separate executable paths on this machine:

- Shell command: `/home/anichols/.local/bin/nanobot`
- Homebrew-managed binary: `/home/linuxbrew/.linuxbrew/opt/nanobot/bin/nanobot`

If the goal is to verify the brew redeploy, use the explicit Homebrew path or inspect the running Homebrew service. Do not assume `nanobot` on PATH is the brew-installed one.
