# Team-message interface revision

The completed pilot did send both board tool descriptions to the provider. Raw Inspect
logs store long strings as attachment references; resolving those references recovers
the actual descriptions. There is no evidence that descriptions were absent.

The interface nevertheless underexplained its purpose. The read description led with
ascending IDs and pagination, the names did not emphasize teammates, and the main
TOOLS AVAILABLE section omitted both board tools. Zero reads in one pilot cannot
establish that naming caused the result, or that voluntary reading generally fails.

Version `team-messages-v2` now exposes:

- `read_team_messages`: See what your teammates have tried, learned, or asked about.
  Explains catching up on earlier work, finding approaches and checking responses;
  explicitly says that a no-argument call opens the board.
- `post_team_message`: Share a finding, question, or update with your teammates.
  Explains asking for help, reporting blockers and replying; points back to reading.

Both tools appear first in the main TOOLS AVAILABLE list. Private scratch remains
private; publication remains explicit. No required reads, automatic exposure, seeded
content, new integrity instruction, scoring change or budget change was introduced.
The matched 12-attempt GLM rerun is complete. Four of six board agents read; one
later agent received and explicitly adopted a published workaround. See the
[completed results](RESULTS.md) for evidence, limits and usage.

[Exact old/new model-visible schemas](model-visible-tools.json). The revised definitions
were extracted from a completed real Inspect/mock-model Docker smoke and serialized
through the installed OpenRouter adapter offline. All183 tests pass. The two-episode
free smoke confirms private reset, public persistence and exact audit/delivery matching
with the new tool names. Its evidence is under
`messageboardbench/logs/board-interface-v2-check-sept8`.

Historical logs, descriptions and results are unchanged. The evidence exporter supports
both old and new tool names; future run manifests record the interface version.
