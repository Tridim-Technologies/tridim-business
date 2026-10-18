# Releases

The `main` branch release workflow uses Python Semantic Release with the
project's Conventional Commit rules. A qualifying merge updates the project
version and lockfile, creates a version commit and tag, then publishes a
GitHub Release. The project does not publish a Python distribution.

## Recovery after a partial release

Python Semantic Release can push the version commit successfully and then fail
while pushing its tag. The workflow runs
[`scripts/semantic_release_with_recovery.py`](../scripts/semantic_release_with_recovery.py)
after the normal release command fails. Recovery proceeds only when all of
these checks pass:

1. The current local commit is exactly the tip of `origin/main`.
2. Exactly one `v<major>.<minor>.<patch>` version tag points at that commit.
3. That tag resolves to the same commit.
4. A push of that exact tag succeeds within three attempts (with short delays
   between attempts).

Only then does the workflow run `semantic-release changelog
--post-to-release-tag <tag>` to create or update the GitHub Release with its
generated changelog. Git refuses to overwrite a conflicting
remote tag because the workflow pushes the explicit tag ref without force.
If any check or retry fails, recovery stops and the job remains failed for
inspection; it does not guess a version or create a new commit.

For a failed release, inspect the [Release workflow run](../.github/workflows/release.yml)
and confirm the remote `main` commit and tag before taking manual action. Do
not rerun `semantic-release version` against a partially completed release
without first checking the remote commit and tags.

## Version rules

- `feat` commits create a minor release.
- `fix` and `perf` commits create a patch release.
- A `!` or `BREAKING CHANGE:` footer creates a major release.
- Documentation, chores and CI-only changes do not create a release.

Use Conventional Commit messages so the version and release notes can be
derived from the project history.
