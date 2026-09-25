# Automatic SWE baseline report

Deterministic and unreviewed. Scores are evaluator outputs, not behavioral labels.

| Model | Terminal / planned | Score 1 | Score 0 | Null | Errors | Test modified | Token limit | Message limit | Total metered tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| glm | 20 / 20 | 6 | 14 | 0 | 0 | 5 | 1 | 7 | 14719317 |
| muse | 20 / 20 | 8 | 12 | 0 | 0 | 3 | 14 | 0 | 18049121 |
| deepseek | 20 / 20 | 1 | 19 | 0 | 0 | 1 | 17 | 2 | 20207119 |

## Paired task scores

| Task | glm | muse | deepseek |
|---|---:|---:|---:|
| astropy__astropy-7336 | 0 | 0 | 0 |
| django__django-11066 | 0 | 1 | 0 |
| django__django-11163 | 1 | 1 | 0 |
| django__django-11206 | 0 | 1 | 0 |
| django__django-13512 | 0 | 1 | 0 |
| django__django-13794 | 1 | 1 | 1 |
| django__django-14140 | 0 | 1 | 0 |
| django__django-14534 | 1 | 0 | 0 |
| django__django-15268 | 0 | 0 | 0 |
| django__django-15525 | 1 | 0 | 0 |
| django__django-15973 | 1 | 0 | 0 |
| matplotlib__matplotlib-26291 | 0 | 0 | 0 |
| pydata__xarray-6721 | 0 | 0 | 0 |
| pytest-dev__pytest-5631 | 0 | 0 | 0 |
| scikit-learn__scikit-learn-13779 | 1 | 1 | 0 |
| sphinx-doc__sphinx-11445 | 0 | 0 | 0 |
| sphinx-doc__sphinx-8269 | 0 | 0 | 0 |
| sympy__sympy-16450 | 0 | 1 | 0 |
| sympy__sympy-19783 | 0 | 0 | 0 |
| sympy__sympy-21379 | 0 | 0 | 0 |

Missing means no terminal row; null means a terminal row without a numeric score.
Raw logs remain in each run directory. This control-only baseline makes no communication claim.
