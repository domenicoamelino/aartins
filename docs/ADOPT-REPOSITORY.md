# Repository workflow and original code

The public repository is https://github.com/domenicoamelino/aartins. This revision is based on its published main history; bundles also preserve the earlier local baseline tags. The original working PoC is preserved as tag `poc-baseline`; the reusable implementation is a later commit. Use `git show poc-baseline:meeting_worker.py` to inspect original source without replacing live files.

To use the delivered bundle, see [installation](INSTALL.md). To publish your own copy, create an empty repository at your chosen Git host, review tracked files and add its actual URL:

```bash
# Bundle clones already have origin; replace its local bundle URL.
git remote set-url origin YOUR_REPOSITORY_URL
git push -u origin main
git push origin poc-baseline
```

This project is MIT licensed. A published repository exists; downloading or checking out this revision does not deploy it to a server. Keep credentials, private deployment inventory, meeting data and databases outside Git; `.gitignore` helps but is not a secret scanner.

See [GitHub publishing instructions](PUBLISH.md) for bundle and source-only upload options.

## Maintain changes

1. Configure your own Git author name/email, create a branch and edit source.
2. Run `python -m unittest discover -s tests -v` and review the diff.
3. Commit with a concrete description and record model/version settings for runtime tests.
4. Deploy reviewed backend files and restart the service while idle. Keep rollback copies/private backups.
5. Deploy Pipe edits separately through WebUI Admin Panel → Functions; preserve admin Valves.
6. Check a short real recording and status recovery before accepting the update.

With the generic install, the service executes from the checkout. Do not switch branches/pull code while jobs run; schedule an idle maintenance window and restart after a reviewed update. A later packaging improvement can separate installed releases from a development checkout.

Original PoC users should retain their current deployed paths and compare the new code before copying anything. Follow [MVP 3.1 adoption](MVP31-STABILIZATION.md) to upgrade the worker, reporter, knowledge module, upload page and recovery helper together; back up the job database, restart idle worker and replace the Pipe. The additive schema migration preserves existing jobs; old settings are not rewritten. See [installation upgrade notes](INSTALL.md).
