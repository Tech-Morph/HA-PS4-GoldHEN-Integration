# Regression checks

The workflow in `.github/workflows/regression.yml` runs the same regression suites used during the HA repair. It runs on pull requests targeting `main`, updates to those PRs, and pushes to `main`. There are no path filters, so documentation-only changes don't leave a required check waiting forever.

Manual dispatch is included. The Actions-tab Run workflow control becomes available once this workflow exists on the default branch.

## Jobs

| Job | What it runs |
|---|---|
| Python 3.13 | Python/JSON syntax checks and all five Python suites |
| Python 3.14 | The same checks on the second Python version |
| Frontend | Panel syntax, klog subscription assertions, and FTP date/escaping assertions on Node 24 |
| Regression | Final gate; succeeds only when the Python matrix and frontend jobs succeed |

The current Python suites contain 56 tests: FTP telemetry 17, connection/setup 13, shared klog 8, full-module FTP handlers 7, and listings 11. The workflow runs each script separately, just like the local commands. The matrix runs those suites on both Python versions; that isn't 112 distinct tests.

There is no pip or npm dependency install for these tests. They use the standard library, Node built-ins, HA interface stubs, and loopback FTP servers. HACS/hassfest validation stays in the existing workflows.

## Safety

The workflow uses GitHub-hosted runners with a read-only `GITHUB_TOKEN`. The official checkout/setup actions are pinned to verified commit SHAs, checkout credentials aren't persisted, and Node package-manager caching is disabled. It uses `pull_request`, not `pull_request_target`.

No personal token or HA credentials are required. The checks don't connect to the real PS4, deploy HA code, run a PRX/payload, publish a release, or merge anything. Job timeouts bound the run, and a newer PR update cancels the previous regression run.

These are regression checks, not a full HA/browser or PS4 compatibility test. Firmware 9.00 validation still needs the reporter's console. PS4StateJSON.prx is under development and is not working; passing CI doesn't change that.

## Before merging

1. Check that the workflow actually ran on the current PR revision.
2. Wait for the Regression gate and the existing HACS/hassfest checks to pass.
3. Add the actual Regression check shown by GitHub to the main/default-branch ruleset. Confirm the real check names before configuring the validators too.
4. Use Squash and merge when the PR is approved for merging, so this PR becomes one commit on main. Don't force-push or delete published main history.
5. Keep issue #1 open until the firmware 9.00 reporter confirms the connection fix.

If no runs appear, check the repository's Actions settings. Workflow files alone don't enable Actions if the repository has disabled or restricted them. After CI is enabled, rerun the existing jobs or push an approved update to retrigger PR validation.
