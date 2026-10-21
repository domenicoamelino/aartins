# Publish your AARTINS repository

This delivery has not published anything. You choose the GitHub account, repository visibility and upload method.

Suggested repository name: **aartins**.

Suggested description:

> Self-hosted audio transcription and summaries with Open WebUI, a Python backend and local AI. Configurable languages, Ollama integration and Markdown archives.

Suggested topics: `open-webui`, `ollama`, `faster-whisper`, `transcription`, `summarization`, `self-hosted`, `local-ai`, `markdown`.

## Preserve the supplied history

Create an empty GitHub repository without generating a README/license/gitignore, because they are already included. On a computer with Git, replace YOUR_GITHUB_USER with your real account:

```bash
git clone /path/to/aartins.bundle aartins
cd aartins
git remote set-url origin https://github.com/YOUR_GITHUB_USER/aartins.git
git push -u origin main
git push origin poc-baseline
```

Normal GitHub authentication is required. The initial commits use a local automation identity; configure your own Git name/email before future changes. The original PoC is retained by tag, not executed by default.

## Upload source only

Alternatively unpack `aartins-source.zip` and upload the **contents** of its `aartins/` folder to the repository root. Include `.gitignore` and `.gitattributes` along with README, LICENSE, source, tests, deploy templates and docs. This method does not retain the supplied commit history or `poc-baseline` tag; use the bundle method when preserving the original implementation matters.

## Finish the public page

- Add the description/topics and confirm README/license are detected.
- Replace placeholder clone URLs in docs/INSTALL.md with your actual GitHub URL after publishing, if desired.
- Follow the installation guide in a fresh checkout and record real model/browser results before claiming broader compatibility.
- Use only synthetic or explicitly shareable content in screenshots/examples.

The source archive and Git bundle contain no private runtime settings or meeting recordings. Future additions still need review: ignore rules cannot protect secrets already committed or deliberately force-added.
