#!/usr/bin/env python3
"""Fails if code quoted in the tutorial no longer matches the real files."""

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUOTE = re.compile(
    r"<code>([\w/.-]+\.(?:py|yaml|html))</code> lines? (\d+)(?:–(\d+))?</span>.*?<pre><code>(.*?)</code></pre>",
    re.S,
)


def main():
    checked, failures = 0, []
    for page in sorted((ROOT / "tutorial").glob("*.html")):
        for match in QUOTE.finditer(page.read_text()):
            path, first, last, body = match.groups()
            first, last = int(first), int(last or first)
            source = ROOT / path
            if not source.exists():
                failures.append(f"{page.name}: {path} does not exist")
                continue
            expected = [line.rstrip() for line in source.read_text().split("\n")[first - 1 : last]]
            quoted = []
            for line in body.split("\n"):
                line = re.sub(r'^<span class="ln">\d+</span>', "", line)
                quoted.append(html.unescape(re.sub(r"<[^>]+>", "", line)).rstrip())
            checked += 1
            if quoted != expected:
                failures.append(f"{page.name}: {path} lines {first}-{last} do not match")
    print(f"Checked {checked} quoted blocks.")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
