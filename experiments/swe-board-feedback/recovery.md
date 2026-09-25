# Recovery

The September 21 first attempt failed before any model response because the
OpenRouter key returned HTTP 403 `Key limit exceeded (total limit)`. The key
reported usage `$15.109426251`, limit `$15`, and no remaining budget before the
first population. GLM, Muse, and DeepSeek each recorded one failed attempt for
all 20 assigned task IDs, for 60 failed attempts total. All had null scores, two
messages, no board or organizer-feedback activity, and zero billed usage delta.

Affected IDs: `astropy__astropy-7336`, `django__django-11066`,
`django__django-11163`, `django__django-11206`, `django__django-13512`,
`django__django-13794`, `django__django-14140`, `django__django-14534`,
`django__django-15268`, `django__django-15525`, `django__django-15973`,
`matplotlib__matplotlib-26291`, `pydata__xarray-6721`,
`pytest-dev__pytest-5631`, `scikit-learn__scikit-learn-13779`,
`sphinx-doc__sphinx-11445`, `sphinx-doc__sphinx-8269`,
`sympy__sympy-16450`, `sympy__sympy-19783`, and `sympy__sympy-21379`.

The failed outputs are temporarily retained as `key-limit-attempt-1` beneath
each model's original log namespace. The canonical `run` paths are free for a
fresh restart with the frozen plans. Remove the failed attempt directories once
the recovery completes and the successful scored attempts are in the canonical
run paths.

After the key limit was reset, the old runner was invoked once more. It treated
the failed rows as terminal, made no model calls, and rewrote summary metadata.
The archived attempt directories therefore contain that no-op invocation as
well as the original failed eval files. Their `failed.json` markers exclude the
entire directories from experiment results.

The fresh GLM phase 1 later produced three scored outcomes and two deterministic
grader-only null outcomes. `pydata__xarray-6721` has a malformed evaluator patch
that prevents test collection. `astropy__astropy-7336` references a test path
that does not exist in its frozen repository revision. Both model trajectories
are retained and must not be rerun. The recovery runner treats an attached
grader diagnostic as a terminal null outcome while continuing to retry failures
that occurred before grading. Its changed bytes and the pre-upgrade eval hashes
are archived separately in the run's `resume-source-snapshot` before any resumed
model call.

Both grader-null assignments were mistakenly attempted twice before this fix.
Recovery selects the earlier trajectory for each assignment and records the later
one as a redundant infrastructure retry. The xarray eval hashes are
`9a0459d359fd61359d9572306746c8c42b86809c79ea9d535b322e41d6c80fbf`
and `9794c69d72b7ff9a9f536e2f5a444e8f5ba835ba12df7c4fd4f416a8ae68e98f`.
The Astropy eval hashes are
`94683c6d5a4e87e600db96b30fa392d687a870e9b20966b807d8393b04d15929`
and `54b65d6d5047b8b79b0a3ac3c12f516a3eae53e83b1c903655f717173c246b0f`.
Keep all four files until the experiment completes, then remove the two later
redundant retry evals before reporting.
