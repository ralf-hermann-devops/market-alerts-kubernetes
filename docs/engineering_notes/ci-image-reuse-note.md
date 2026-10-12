# CI image reuse note

## Context

Image scanning, application tests, and Kubernetes tests all need the API, worker, and fetcher images. Building them separately duplicates work and may produce different artifacts across jobs.

## Implemented approach

1. Build the service images once in a dedicated CI job
2. save them as a Docker archive
3. upload the archive as a workflow artifact
4. and download and load the same images where needed

This reduces repeated build and keeps a logical flow in the pipeline: build once, distribute, then validate. It also ensures that scans and tests operate on the same image artifacts.

## Performance note

As a rough estimate, the repeated-build pipeline uses approximately 35 seconds per build across five consumers:

- 35 seconds x 5 consumers = 175 seconds of aggregate compute

By contrast, building once and then distributing the archive is estimated at:

- 45 seconds for the image build and archive upload
- 15 seconds for each of five downloads and loads
- 15 seconds x 5 = 75 seconds
- 45 + 75 = 120 seconds of aggregate compute

So in this estimate, a single shared build and distribution path reduces the aggregate compute from roughly 175 seconds to approximately 120 seconds. The savings are modest for the current image set, but they become more meaningful as image build complexity increases or more jobs begin consuming the same images.

## Trade-offs

- Artifact upload, download, and image loading add workflow steps and increase the start to finish pipeline run time.
- Large images can make the archive significantly larger, increasing upload and download time, storage use, and transfer strain.

Important note: all numbers used here are approximate and vary slightly between runs and steps. The expected resource saving is modest for the current images.

## Implementation details

- Build the `api`, `worker`, and `fetcher` images once with Docker Compose.
- Save the `trading-api:dev`, `trading-worker:dev`, and `trading-fetcher:dev` images to a single archive and upload it as a workflow artifact.
- Reuse a local composite action to download the archive and load it where needed
- Keep the archive filename and artifact name shared through workflow-level variables and composite-action inputs.