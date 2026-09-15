# SWE-bench infrastructure validation

This track is an external-validity staging exercise. It does not call a behavioral
model and its output is not evidence about communication or cheating.

Install the isolated optional dependencies, then restore the editable ImpossibleBench
install that `uv sync` removes:

```sh
just swe-install
```

Preview a paired record at an immutable dataset revision without starting Docker:

```sh
just swe-preview --revision REVISION_SHA --instance-id INSTANCE --out work/swe-check
```

After reviewing the pair, run the four-cell no-model matrix:

```sh
just swe-validate --revision REVISION_SHA --instance-id INSTANCE \
  --audit work/swe-audit.json --out work/swe-check
```

The executable refuses every Docker daemon except
`ssh://pj@100.68.126.75` reporting `linux/amd64`. Source and Python remain local.
The Docker client streams only the selected test and oracle patches into a fresh
ephemeral container; the repository is never staged on the Docker host. Each container
uses `--network none`, an 8 GiB default memory limit, and the registry image resolved by
SWE-bench 4.1.0's `make_test_spec` API.

The gate requires:

- the original and conflicting rows to share instance, repository, version, base
  commit and oracle patch;
- the conflicting row to preserve the exact original test patch and add a distinct
  test patch;
- every patch check/application to succeed;
- the original no-change run to fail, original oracle to resolve, and both conflicting
  runs to remain unresolved;
- all declared `FAIL_TO_PASS` and `PASS_TO_PASS` targets to be present in output parsed
  by SWE-bench's repository-specific parser.

Execution additionally requires a human-authored audit JSON bound to the manifest's
dataset, revision, instance and three patch hashes. It must contain nonempty `reviewer`,
`reviewed_at`, and `contradiction_description` fields plus
`"same_input_contradiction_reviewed": true`. The reviewer must inspect the issue,
oracle patch, both test patches, and confirm that the added test contradicts required
behavior for the same input; a merely difficult or broken setup is not sufficient.

Each trial records the remote image ID and repository digest returned by Docker, and
the gate fails if any trial differs. Resolution deliberately requires both a zero
process exit code and successful SWE-bench parsing of every declared target. This is
stricter than the historical behavior scorer because readiness must reject collection,
parser, or missing-test failures instead of treating shell success alone as evidence.

Raw stdout/stderr and hashes are written under the requested ignored `work/` directory.
Do not promote a bundle to `results/` until the added contradiction, collected tests,
and per-test statuses have been reviewed. Passing this gate establishes infrastructure
readiness for one paired instance only. Multiple distinct audited IDs are still needed
for a communication experiment, and the neutral board solver has not yet been adapted
to SWE repositories.
