#!/usr/bin/env python3
"""Fetches SigNoz's official agent skills into Lab 5's workspace.

They come from https://github.com/SigNoz/agent-skills (MIT), pinned to one
commit so upstream changes can't change the lab's results. A skill is a
written procedure the agent loads when it's relevant. These three are
read-only:

- signoz-investigating-alerts: why an alert fired, in tiers that stop early.
- signoz-generating-queries: how to write SigNoz queries for a question.
- signoz-explaining-alerts: what a rule checks, and how it's evaluated.

They go into labs/lab5-ai/workspace/.claude/skills/, which Claude Code reads
when it starts in the workspace. They aren't committed to this repo.
"""

import subprocess
from pathlib import Path

COMMIT = "23d7c32382c1686d9b5c3d23ec4d15b15fdbcb66"
SKILLS = {
    "signoz-investigating-alerts": ["SKILL.md", "references/baseline-comparison.md", "references/neighbor-signals.md"],
    "signoz-generating-queries": ["SKILL.md", "references/ai-queries.md"],
    "signoz-explaining-alerts": ["SKILL.md"],
}
BASE = f"https://raw.githubusercontent.com/SigNoz/agent-skills/{COMMIT}"
TARGET = Path(__file__).resolve().parent.parent / "labs/lab5-ai/workspace/.claude/skills"


def main():
    for skill, files in SKILLS.items():
        for name in files:
            path = TARGET / skill / name
            path.parent.mkdir(parents=True, exist_ok=True)
            # curl, because python.org's Python on macOS has no root certificates.
            subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(path), f"{BASE}/plugins/signoz/skills/{skill}/{name}"], check=True)
    (TARGET / "LICENSE-signoz-agent-skills").write_text(
        subprocess.run(["curl", "-fsSL", "--retry", "3", f"{BASE}/LICENSE"], check=True, capture_output=True, text=True).stdout
    )
    print(f"Fetched {len(SKILLS)} SigNoz skills at {COMMIT[:12]} into {TARGET.relative_to(TARGET.parents[4])}.")


if __name__ == "__main__":
    main()
