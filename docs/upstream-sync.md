# Upstream Sync

`Thetromboneman1/APEX` tracks `lowiqentity/APEX` while preserving the downstream feed changes on `main`.

## Automated path

`.github/workflows/upstream-sync.yml` runs weekly and supports manual dispatch. It fetches upstream `main`, creates an `automation/upstream-sync-<base-sha>-<upstream-sha>` review branch, merges there, runs `scripts/validate-downstream.sh`, and opens or reuses a pull request only after validation passes. It never force-pushes or rewrites downstream history.

If the merge conflicts, the workflow lists the files in the run summary, aborts the merge, and leaves `main` unchanged. Resolve those conflicts in a separate review branch. Do not change the workflow to prefer one side automatically because the JSON feeds contain downstream publishing decisions.

## Reviewed reconciliation (2026-10-11)

The review branch incorporates upstream `7ebd266` while preserving the fork's
publishing identity. Only upstream-generated feed data changed since the last
reviewed ancestor (`f03d56d`); the generator and configuration did not change.

The four conflicting files were regenerated, rather than copied from either
side, with:

```sh
GITHUB_REPOSITORY=Thetromboneman1/APEX GITHUB_REF_NAME=main \
  python3 scripts/generate_release_feeds.py
scripts/validate-downstream.sh
```

The fork's [release inventory](https://api.github.com/repos/Thetromboneman1/APEX/releases)
was empty at review time. The regenerated feeds therefore retain
`com.thetromboneman1.apex`, fork-owned URLs, and empty `apps` lists. Their bytes
match downstream `9697414`; upstream's external IPA links are not releases
published by this fork and were not imported. This preserves the same decision
made in [the previous reconciliation](https://github.com/Thetromboneman1/APEX/pull/2).
The merge records upstream ancestry even though the generated downstream feed
contents do not change.

Local regeneration and `scripts/validate-downstream.sh` both passed. All four
files parsed as JSON and `feather.json` matched `store.json`. Daily feed
[generation run 38097619603](https://github.com/Thetromboneman1/APEX/actions/runs/38097619603)
also completed successfully. Future release inventories must be checked again
before resolving a later conflict; do not turn this decision into an automatic
preference for either side.

## Manual reconciliation

1. Create a branch from the current downstream `main`.
2. Fetch `lowiqentity/APEX` as a separate upstream remote.
3. Merge upstream `main` without committing.
4. Review each conflicting feed entry against the downstream signing and distribution intent.
5. Run `scripts/validate-downstream.sh` and validate each edited JSON file with `jq empty`.
6. Commit the reviewed merge, push the branch, and use a pull request to preserve the decision trail.

Stop if a feed entry's intended signing source or distribution owner cannot be proven. Record the unresolved item instead of forcing the merge to balance.

