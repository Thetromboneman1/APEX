# Upstream Sync

`Thetromboneman1/APEX` tracks `lowiqentity/APEX` while preserving the downstream feed changes on `main`.

## Automated path

`.github/workflows/upstream-sync.yml` runs weekly and supports manual dispatch. It fetches upstream `main`, creates an `automation/upstream-sync-<sha>` review branch, merges there, runs `scripts/validate-downstream.sh`, and opens a pull request only after validation passes. It never force-pushes or rewrites downstream history.

If the merge conflicts, the workflow lists the files in the run summary, aborts the merge, and leaves `main` unchanged. Resolve those conflicts in a separate review branch. Do not change the workflow to prefer one side automatically because the JSON feeds contain downstream publishing decisions.

## Current manual review

Run `32943354358` stopped safely on conflicts in:

- `JSON/esign.json`
- `JSON/feather.json`
- `JSON/scarlet.json`
- `JSON/store.json`

The feed generator remains healthy. Scheduled run `33029440372` completed successfully on August 27, 2026.

## Manual reconciliation

1. Create a branch from the current downstream `main`.
2. Fetch `lowiqentity/APEX` as a separate upstream remote.
3. Merge upstream `main` without committing.
4. Review each conflicting feed entry against the downstream signing and distribution intent.
5. Run `scripts/validate-downstream.sh` and validate each edited JSON file with `jq empty`.
6. Commit the reviewed merge, push the branch, and use a pull request to preserve the decision trail.

Stop if a feed entry's intended signing source or distribution owner cannot be proven. Record the unresolved item instead of forcing the merge to balance.

