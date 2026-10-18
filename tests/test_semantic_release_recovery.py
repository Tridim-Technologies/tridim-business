"""Tests for guarded recovery of a partially pushed semantic release."""

from __future__ import annotations

import subprocess
import unittest
from collections.abc import Sequence
from scripts.semantic_release_with_recovery import recover_release


class SemanticReleaseRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reads: list[Sequence[str]] = []
        self.commands: list[Sequence[str]] = []
        self.delays: list[float] = []
        self.outputs = iter(
            [
                "release-commit",
                "release-commit\trefs/heads/main",
                "v0.19.0",
                "release-commit",
            ]
        )
        self.returncodes = iter([0, 0])

    def read_output(self, command: Sequence[str]) -> str:
        self.reads.append(command)
        return next(self.outputs)

    def run_command(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, next(self.returncodes))

    def recover(self) -> None:
        recover_release(
            command_runner=self.run_command,
            output_reader=self.read_output,
            sleep=self.delays.append,
        )

    def test_retries_tag_push_then_publishes_the_verified_tag(self) -> None:
        self.returncodes = iter([1, 0, 0])

        self.recover()

        refspec = "refs/tags/v0.19.0:refs/tags/v0.19.0"
        self.assertEqual(
            self.commands,
            [
                ["git", "push", "origin", refspec],
                ["git", "push", "origin", refspec],
                [
                    "uv",
                    "run",
                    "semantic-release",
                    "changelog",
                    "--post-to-release-tag",
                    "v0.19.0",
                ],
            ],
        )
        self.assertEqual(self.delays, [2])

    def test_refuses_to_push_when_remote_main_is_not_the_release_commit(self) -> None:
        self.outputs = iter(["release-commit", "other-commit\trefs/heads/main"])

        with self.assertRaisesRegex(RuntimeError, "not the current origin/main tip"):
            self.recover()

        self.assertEqual(self.commands, [])

    def test_refuses_ambiguous_or_missing_tags(self) -> None:
        self.outputs = iter(["release-commit", "release-commit\trefs/heads/main", ""])

        with self.assertRaisesRegex(RuntimeError, "exactly one version tag"):
            self.recover()

        self.assertEqual(self.commands, [])

    def test_refuses_tag_that_points_to_a_different_commit(self) -> None:
        self.outputs = iter(
            [
                "release-commit",
                "release-commit\trefs/heads/main",
                "v0.19.0",
                "other-commit",
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "does not point to"):
            self.recover()

        self.assertEqual(self.commands, [])

    def test_does_not_publish_when_tag_push_never_succeeds(self) -> None:
        self.returncodes = iter([1, 1, 1])

        with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
            self.recover()

        self.assertEqual(
            self.commands[-1],
            ["git", "push", "origin", "refs/tags/v0.19.0:refs/tags/v0.19.0"],
        )
        self.assertEqual(len(self.commands), 3)
        self.assertEqual(self.delays, [2, 5])

    def test_surfaces_release_creation_failure_after_tag_push(self) -> None:
        self.returncodes = iter([0, 1])

        with self.assertRaisesRegex(RuntimeError, "could not create or update"):
            self.recover()

        self.assertEqual(len(self.commands), 2)


if __name__ == "__main__":
    unittest.main()
