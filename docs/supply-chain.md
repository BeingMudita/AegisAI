# Supply chain

How AegisAI makes sure the code, the containers and the models it runs are the
ones that were reviewed. This is Phase 13 and covers OWASP LLM03 (Supply Chain)
and MITRE ATLAS AML.T0010 (ML Supply Chain Compromise).

| Layer | Control | Where |
|---|---|---|
| Python packages | Every package (direct and transitive) pinned with hashes; `pip-audit` in CI | `backend/requirements.lock` |
| npm packages | Lockfile + `npm ci`; `npm audit` on shipped dependencies in CI | `frontend/package-lock.json` |
| CI itself | Every GitHub Action pinned to a full commit SHA | `.github/workflows/ci.yml` |
| Container images | Trivy scans both images; a fixable HIGH or CRITICAL fails the build. Dockerfiles are checked for misconfigurations, and both images run as non-root | `supply-chain` CI job, `.trivyignore` |
| Models | Pinned in a manifest and verified before use | `backend/model-manifest.yaml` |
| Inventory | CycloneDX 1.6 SBOMs for the code and the images, and an AI-BOM for the models | `sbom` CI artifact |

Dependabot proposes weekly updates for pip, npm, GitHub Actions and Docker
base images.

## Model provenance

`backend/model-manifest.yaml` lists every model AegisAI may load.

- **Hugging Face models** (the embedder) are pinned to a commit, never a branch
  or tag, along with the SHA-256 of every file the loader reads. At load time
  AegisAI downloads only those files at that commit and hashes each one. It
  then loads the model from that verified local copy, so the files that were
  checked are the files that run.
- **Ollama models** (the planner LLM) are pinned by manifest digest, which is
  the ID that `ollama list` shows. The manifest names every layer (weights,
  chat template, parameters) by its SHA-256, and Ollama verifies each layer
  when it pulls. So one digest pins the whole model, chat template included.
  A swapped template is an injection vector of its own.

`MODEL_PROVENANCE` controls what happens when a check fails:

| Mode | Unpinned or altered model |
|---|---|
| `enforce` (default) | Refused. The embedder raises `ProvenanceError`. The planner falls back to the deterministic rule-based brain, so the agent stays inside its policy. |
| `warn` | Used anyway. |
| `off` | Not checked. |

In `enforce` and `warn` mode a failed check also records an `ANOMALY` security
event from `supply_chain`: severity HIGH when the model is refused, MEDIUM when
it is used anyway.

To see the checks:

```bash
aegis verify-models           # check the configured models now; exit 1 if any is refused
aegis aibom -o models.cdx.json  # the pins as a CycloneDX AI-BOM
```

Both are also available over the API, to any signed-in user:

- `GET /api/supply-chain` returns the manifest, the mode, and every check since
  the server started.
- `GET /api/supply-chain/aibom` returns the AI-BOM.

### How the pins were obtained

- **Hugging Face.** The commit and the weight hashes come from
  `https://huggingface.co/api/models/<repo>/revision/<commit>?blobs=true`. That
  endpoint gives the SHA-256 of large (LFS) files. Small files were downloaded
  at the commit and hashed. Each download was cross-checked against the git
  blob ID the Hub reports for it.
- **Ollama.** The digest is the SHA-256 of the manifest that
  `registry.ollama.ai/v2/library/<model>/manifests/<tag>` serves. It is the
  same value `ollama list` shows as the model's ID.

### Updating a pin

Do this when you upgrade a model or add a new one. Treat it as a reviewed
change:

1. Get the new values with the steps above.
2. Edit `model-manifest.yaml`.
3. Run `aegis verify-models` on a machine that has the model.
4. Re-run the evaluation. A different embedder changes retrieval, and a
   different LLM changes planning.
5. Re-index the knowledge base if the embedder changed.

## SBOMs

The `supply-chain` CI job uploads an `sbom` artifact with five files:

| File | Contents |
|---|---|
| `backend.cdx.json` | Python runtime dependencies, from the hashed lockfile |
| `frontend.cdx.json` | npm dependencies shipped in the dashboard |
| `models.cdx.json` | The pinned models, as CycloneDX `machine-learning-model` components with per-file hashes |
| `backend-image.cdx.json`, `frontend-image.cdx.json` | Everything in each container image, OS packages included |

To generate the code SBOMs locally:

```bash
cd backend  && uvx --from cyclonedx-bom==7.5.0 cyclonedx-py requirements requirements.lock \
                 --pyproject pyproject.toml --sv 1.6 --of JSON -o ../sbom/backend.cdx.json
cd frontend && npx @cyclonedx/cyclonedx-npm@6.0.1 --omit dev --spec-version 1.6 \
                 --output-file ../sbom/frontend.cdx.json
```

## Accepting a vulnerability

CI fails on any image vulnerability that has a fix. If one can't be fixed yet
and isn't reachable, add its ID to `.trivyignore`. Include the reason and a
date to revisit it. Never add an ID just to turn the build green.

## Not covered

- **Publisher signatures.** A pin proves the model is the one that was
  reviewed, not that its publisher is trustworthy. There is no Sigstore or
  model-signing verification yet.
- **Training-data provenance.** This is out of scope, since AegisAI doesn't
  train models.
- **Scanner coverage.** Image scanning finds known CVEs only.
