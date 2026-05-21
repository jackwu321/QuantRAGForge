# Releasing (maintainers)

This repo publishes to PyPI automatically when a `v*.*.*` tag is pushed. The workflow is defined in [`.github/workflows/publish.yml`](../.github/workflows/publish.yml) and uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) — no API token is stored in GitHub secrets.

## One-time PyPI setup

Before the first release, configure a "pending publisher" on PyPI:

1. Log in to https://pypi.org/manage/account/publishing/
2. Add a pending publisher with:
   - **PyPI Project Name:** `quant-llm-wiki`
   - **Owner:** `jackwu321`
   - **Repository name:** `Quant_LLM_Wiki`
   - **Workflow filename:** `publish.yml`
   - **Environment name:** `pypi`
3. In GitHub repo settings → Environments, create an environment named `pypi` (no secrets needed; OIDC handles auth).

## Cutting a release

```bash
# 1. Bump version in pyproject.toml (e.g. 0.4.6 -> 0.4.7)
# 2. Update CHANGELOG.md
# 3. Commit
git commit -am "release: v0.4.7"
# 4. Tag and push
git tag v0.4.7
git push origin main --tags
```

The workflow will:

1. Verify the tag matches `project.version` in `pyproject.toml`
2. Build sdist + wheel
3. Upload to PyPI via Trusted Publishing

Users then upgrade with `pipx upgrade quant-llm-wiki`.

> **Versioning.** Follow [SemVer](https://semver.org/): bump patch for fixes, minor for new features, major for breaking changes. The tag `v0.4.7` must match `version = "0.4.7"` in `pyproject.toml` exactly, or the workflow aborts before publishing.
