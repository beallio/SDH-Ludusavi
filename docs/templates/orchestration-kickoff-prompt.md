Use the /orchestrated-implementation skill.

Use the implementation plan that was just created under docs/plans/.

Infer TITLE, SLUG, and PLAN_PATH from the plan.

Manage the full lifecycle:
1. verify the plan contains the required orchestration contract;
2. start the implementer with scripts/orchestration/start-implementer <SLUG>;
3. wait for the round-complete marker with scripts/orchestration/wait-for-finished <SLUG>;
4. review the implementation against the plan;
5. if changes are needed, write and commit a CHANGES_REQUESTED review note under docs/review/;
6. after committing the review note, resume the implementer with scripts/orchestration/continue-implementer <SLUG>;
7. repeat review rounds until approved;
8. write and commit an APPROVED review note;
9. resume the implementer with scripts/orchestration/continue-implementer <SLUG>;
10. wait for the finalized marker with scripts/orchestration/wait-for-finalized <SLUG>;
11. stop the implementer with scripts/orchestration/stop-implementer <SLUG>.

Do not ask me to manage tmux manually.
Do not start continue-implementer before the review note is written and committed.
Do not stop the implementer until the finalized marker exists.
Do not implement the feature yourself unless explicitly necessary to recover from a blocked state.