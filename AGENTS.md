# VibeStick-Codex Repository Rules

These instructions apply to the entire repository.

## GitHub synchronization privacy gate

Treat every commit as if the repository will become public, even while the
GitHub repository is private.

When the user asks to commit, push, publish, open a pull request, or
"同步 GitHub", interpret the request as:

> 检查隐私后同步 GitHub

Before any GitHub synchronization:

1. Inspect `git status`, the complete working-tree diff, the staged diff, and
   every untracked file. Do not use `git add .` until each untracked file has
   been reviewed and intentionally included.
2. Check the proposed commit for secrets and personal data, including API keys,
   access tokens, passwords, Wi-Fi credentials, private email addresses, phone
   numbers, local absolute paths, device identifiers, recordings, transcripts,
   logs, screenshots, and raw service responses.
3. Confirm local-only files remain untracked and ignored, especially `.env`,
   `*.token`, `*.key`, `vibe_stick_secrets.h`, `sdkconfig*`, recordings, logs,
   state files, and build outputs. Never print secret values merely to perform
   this check.
4. Confirm the project owner's new commits use the GitHub `noreply` email
   configured for this checkout. Preserve legitimate upstream contributor
   attribution.
5. Run checks appropriate to the change, including tests and firmware builds
   when affected.
6. Report the privacy-check result before pushing. If any possible exposure is
   found, stop and remove or redact it before synchronization.

Do not force-push, rewrite published history, or delete remote data unless the
user explicitly authorizes that exact destructive action.
