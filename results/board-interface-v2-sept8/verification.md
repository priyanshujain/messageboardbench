# Independent run verification

Run complete: True. Checked 12 archived task inputs and 12 completed sample logs. Failed boolean checks: 0.

The task text, test bytes, entry points, task schedule, model, execution limits, and generation settings are compared with the prior GLM pilot. Completed samples are checked against the exact prior baseline prompt plus the intended v2 interface additions, with new episode identities. Source archive hashes and current source are checked separately.

Manifest differences:
```json
{
  "board_interface_version": {
    "old": null,
    "new": "team-messages-v2"
  },
  "limitations": {
    "old": [
      "One team per condition; development cases, not rate estimates.",
      "90 messages exceeds the 60-message model diagnostic.",
      "Tool descriptions and advertised access are part of the intervention.",
      "Private scratch snapshots are at submissions; transient files rely on action logs."
    ],
    "new": [
      "One team per condition; development cases, not rate estimates.",
      "Message limit 90; preliminary model diagnostic used 60.",
      "Tool descriptions and advertised access are part of the intervention.",
      "Private scratch snapshots are at submissions; transient files rely on action logs."
    ]
  }
}
```

See verification.json for per-sample checks and log hashes. All 12 episodes completed; all 12 exact prompts and configurations are verified. Interface changes are bundled and are not a naming-only intervention.

## Final export checks

- twelve_episodes: True
- all_log_hashes_valid: True
- board_hash_valid: True
- report_script_hash_valid: True
- all_operations_delivery_confirmed: True
- no_unmatched_audit: True
- all_token_totals_consistent: True
- all_samples_success_no_error_no_limit: True
- all_unique_episode_identities: True
- schedule_equal_v1: True

Verified 13 source archive hashes, 12 completed log hashes, the final board snapshot hash, and the report script hash. All recorded board operations were linked to delivered tool output; exported token totals balance for all episodes.
