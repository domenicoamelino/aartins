# Publish or adopt the stabilization revision

The project is now **SMARTINI’s**, currently hosted at [domenicoamelino/aartins](https://github.com/domenicoamelino/aartins).
This revision is based on its uploaded main commit `cf3aa0d` rather than replacing
that history. Earlier original PoC and portable source are retained in bundle tags
`poc-baseline` and `aartins-portable-baseline`.

Review the stabilization branch/PR before merging it. A merge updates source only:
it does not deploy files, pull images, change credentials or restart the server.
Use [release adoption](MVP31-STABILIZATION.md) in a planned idle maintenance window.
Keep the personal operations handbook in a separate private location.

For an offline copy containing history:

```bash
git clone -b smartinis-branding /path/to/smartinis.bundle smartinis
cd smartinis
git remote set-url origin https://github.com/domenicoamelino/aartins.git
python3 tools/check_all.py
```

The supplied ZIP is an alternative source snapshot, without Git history. Include
hidden `.gitignore` and `.gitattributes` if transferring its contents manually.
Do not overwrite an existing checkout's `.git` directory or force-push main to
resolve unrelated history. Fetch/review the GitHub branch instead.

The commits use a local snapshot automation identity, not a claimed user authorship
identity. Configure your own Git name/email for future work. MIT licensing of this
source does not replace prerequisite software/model licenses. Runtime settings,
tokens, meeting archives, snapshots and databases must remain outside public Git.
