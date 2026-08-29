# HANDOFF

- Formal main/base: `main@142b7345a5640b1e87932e41f3dc9311172bf54c0`.
- Current task: P0 production market data stability hotfix, PR #31 (`hotfix/production-market-data-stability`).
- Phase 5J-v4 research is paused and unmodified. Final OOS remains sealed/unread. Frozen research and formal artifacts are unchanged.
- The hotfix keeps latest/full isolation: scheduled latest has no historical bulk fetch/write, qfq, SETUP_03, or Decision, and `history_rows_written=0`; manual full remains compatible.
- Sol's stale-both blocker was fixed with a deterministic ordinary-calendar freshness guard separate from source consensus. A stale latest source date may remain visible, but cannot be `已验证` or `SUCCESS`.
- Unfinished: Sol re-audit and approval. Next step after approval is squash merge; do not merge before that.
- Avoid: treating source consensus as freshness proof; restoring scheduled history bulk writes; allowing production latest to call qfq/SETUP_03; relaxing validation to remove `待复核`.

`HANDOFF_CURRENT_AND_CONSISTENT`
