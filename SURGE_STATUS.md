# SURGE STATUS — PAY-MEMANTO

- Operation id: MEMANTO-1852-PR2024
- Lane: PAY-MEMANTO
- Session: https://claude.ai/code/session_01HK841PNnbjZXxreumhR1jT (session_01HK841PNnbjZXxreumhR1jT)
- Model: session_context.model = claude-opus-5-5; external_metadata.last_served_model = claude-opus-5-5
- Updated: 2026-09-22 (milestone 1: provider stage read)
- Deadline: 2026-09-30 23:59 UTC

## Provider stage (as read 2026-09-22)

- Issue moorcheh-ai/memanto#1852: OPEN. "[BOUNTY $100] The Memanto Security Challenge". $100 to top submission on the leaderboard. Labels: Bounty #7, Security Hardening. No comments visible.
- PR moorcheh-ai/memanto#2024: OPEN, not merged, head `woahwhattheheck:fix/1852-local-sync-scope-20260920` @ `1b8e336c16f5ce14a975101f47b0426c680d1bc9`, base `main`. Body says "For #1852". Awaiting maintainer approving review.
- Sponsor mechanism (from issue body, verbatim points):
  - Step 4: "Fork this repo and create a Pull Request (required by BountyHub) ... Your PR description must contain a summary of the flaw, reproduction steps, and your patch." — PR is described as "your official bounty claim".
  - Step 7: "Before the deadline, claim this bounty on BountyHub and attach your PR link. Unclaimed submissions, no matter how good, are not eligible for the payout."
  - So the required claim is a **BountyHub-site claim with the PR link attached** (step 7). There is no comment command on the issue or PR in the instructions. A PR-side claim comment is NOT the mechanism.
- BountyHub claim under woahwhattheheck: NOT VISIBLE FROM GITHUB. No BountyHub bot comments on #1852 or #2024. Existence and PR attachment can only be verified on the BountyHub bounty page for moorcheh-ai/memanto#1852 while signed in as woahwhattheheck (owner-only web page). The Sep 20 finance handoff reported the attachment missing; nothing on GitHub contradicts that.

## CI / mergeability

- Upstream main moved 3 commits since PR base (04e0ba2 -> 7d81404). `git merge-tree` shows NO conflict.
- Upstream CI (`ci.yml`) runs only on push to main or on an approving `pull_request_review`; it cannot run on the PR until a maintainer approves. Only `Auto-label Bounties and PRs` (completed) and `TypeScript SDK` show on the PR. CodeRabbit pre-merge check warns docstring coverage 18.6% (<80%), non-blocking warning.
- In progress: reproducing CI (ruff, ruff format, mypy, pytest) locally on the PR head.

## waiting_on_us vs waiting_on_them

- waiting_on_us: BountyHub claim + PR link attach (owner web step); local CI verification.
- waiting_on_them: maintainer approving review (also gates CI), scoring.

## Blockers

- This session cannot call GitHub API for moorcheh-ai/memanto (add_repo push refused: cross-owner add not supported). Sponsor-side reads were done via public web pages; PR body edits on the sponsor repo cannot be made from this session.

## Money at risk

- $100 USD (winner-take-all, top of leaderboard). Ineligible without the BountyHub claim by 2026-09-30 23:59 UTC.

## URLs relied on

- https://github.com/moorcheh-ai/memanto/issues/1852
- https://github.com/moorcheh-ai/memanto/pull/2024
- https://github.com/moorcheh-ai/memanto/pull/2024/checks
- https://github.com/moorcheh-ai/memanto/blob/main/CONTRIBUTING.md
- https://github.com/moorcheh-ai/memanto/blob/main/.github/workflows/ci.yml
- https://github.com/woahwhattheheck/memanto/tree/fix/1852-local-sync-scope-20260920
