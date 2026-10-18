"""Run Python Semantic Release and safely recover a partially pushed release."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence

VERSION_TAG = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
PUSH_ATTEMPTS = 3
PUSH_RETRY_DELAYS = (2, 5)


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a command while leaving its output visible in the workflow log."""
    return subprocess.run(command, check=False, text=True)


def read_output(command: Sequence[str]) -> str:
    """Run a read-only command and return its trimmed stdout."""
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def recover_release(
    *,
    command_runner: Callable[
        [Sequence[str]], subprocess.CompletedProcess[str]
    ] = run_command,
    output_reader: Callable[[Sequence[str]], str] = read_output,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Retry a release tag and VCS publication only for a verified partial release."""
    local_commit = output_reader(["git", "rev-parse", "HEAD"])
    remote_main = output_reader(
        ["git", "ls-remote", "origin", "refs/heads/main"]
    ).split()
    if not remote_main or remote_main[0] != local_commit:
        raise RuntimeError(
            "The local release commit is not the current origin/main tip; "
            "refusing to push a release tag."
        )

    tags = output_reader(
        ["git", "tag", "--points-at", "HEAD", "--list", "v*"]
    ).splitlines()
    if len(tags) != 1 or not VERSION_TAG.fullmatch(tags[0]):
        raise RuntimeError(
            "Expected exactly one version tag on the current release commit; "
            f"found {tags!r}."
        )

    tag = tags[0]
    tagged_commit = output_reader(["git", "rev-parse", f"{tag}^{{commit}}"])
    if tagged_commit != local_commit:
        raise RuntimeError(
            f"Local tag {tag} does not point to the verified origin/main commit."
        )

    refspec = f"refs/tags/{tag}:refs/tags/{tag}"
    for attempt in range(PUSH_ATTEMPTS):
        result = command_runner(["git", "push", "origin", refspec])
        if result.returncode == 0:
            break
        if attempt == PUSH_ATTEMPTS - 1:
            raise RuntimeError(f"Could not push {tag} after {PUSH_ATTEMPTS} attempts.")
        delay = PUSH_RETRY_DELAYS[attempt]
        print(
            f"Tag push for {tag} failed; retrying in {delay} seconds "
            f"({attempt + 2}/{PUSH_ATTEMPTS}).",
            file=sys.stderr,
        )
        sleep(delay)

    publish = command_runner(
        [
            "uv",
            "run",
            "semantic-release",
            "changelog",
            "--post-to-release-tag",
            tag,
        ]
    )
    if publish.returncode != 0:
        raise RuntimeError(
            f"Python Semantic Release could not create or update the release for {tag}."
        )


def main() -> int:
    """Run release, then attempt only the safe partial-release recovery."""
    release = run_command(["uv", "run", "semantic-release", "version"])
    if release.returncode == 0:
        return 0

    print(
        "Semantic release version failed; checking whether only the tag or "
        "GitHub release remains to be published.",
        file=sys.stderr,
    )
    try:
        recover_release()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Release recovery stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
