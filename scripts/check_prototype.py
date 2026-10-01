"""Check the static workflow prototype's markup and inline JavaScript syntax."""

from __future__ import annotations

import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype/job-to-cash/index.html"


class PrototypeParser(HTMLParser):
    """Reject malformed tokenization and accidental patch artifacts."""

    def error(self, message: str) -> None:
        raise ValueError(message)


def main() -> None:
    source = PROTOTYPE.read_text(encoding="utf-8")
    if re.search(r"(?m)^\+(?:</?(?:style|script)|(?:var|function|document))", source):
        raise SystemExit("Prototype contains stray '+' patch markers")
    parser = PrototypeParser(convert_charrefs=True)
    parser.feed(source)
    parser.close()

    scripts = re.findall(r"<script\b[^>]*>(.*?)</script\s*>", source, re.I | re.S)
    if not scripts:
        raise SystemExit("Prototype must contain its expected inline script")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as script:
        script.write("\n".join(scripts))
        script.flush()
        subprocess.run(["node", "--check", script.name], check=True)


if __name__ == "__main__":
    main()
