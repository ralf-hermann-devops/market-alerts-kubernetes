# CI image reuse note

## Context

The image-scan matrix, the Docker-based application tests and kubernetes in-cluster tests each need the API, worker, and fetcher images. Each job building its own images keeps jobs self-contained and can make the overall workflow finish sooner because the builds run in parallel. However, it repeats expensive work and increases aggregate runner compute.
That is operationally simple, but it creates duplicate work and makes the validation jobs less deterministic because they are not guaranteed to consume the same image artifacts from a single upstream build.

## Proposed approach

Build the service images once in a dedicated CI job, save them as a Docker archive, upload the archive as a workflow artifact, and download and load the same images in the scan and test jobs. This reduces repeated build work while keeping the pipeline explicit: build once, distribute, then validate. It also ensures that scans and tests operate on the same image artifacts.

## Performance note

As a rough estimate, the repeated-build pipeline uses approximately 35 seconds per build across five consumers:

- 35 seconds x 5 consumers = 175 seconds of aggregate compute

By contrast, building once and then distributing the archive is estimated at:

- 45 seconds for the image build and archive upload
- 15 seconds for each of five downloads and loads
- 15 seconds x 5 = 75 seconds
- 45 + 75 = 120 seconds of aggregate compute

So in this estimate, a single shared build and distribution path reduces the aggregate compute from roughly 175 seconds to approximately 120 seconds. The savings are modest for the current image set, but they become more meaningful as image complexity increases or more jobs begin consuming the same images.

## Trade-offs

- Artifact upload, download, and image loading add workflow steps and increase the start to finish pipeline run time.
- Large images can make the archive significantly larger, increasing upload and download time, storage use, and transfer strain.
- The current benefit is not dramatic: the rough estimate moves the pipeline from about 1 minute 40 seconds to about 2 minutes 15 seconds.
- If transfer overhead becomes a bottleneck, this approach should be reassessed.

Important note: all numbers used here are approximate and vary slightly between runs and steps. The expected resource saving is modest for the current images.

## Implementation details

- Build the `api`, `worker`, and `fetcher` images once with Docker Compose.
- Save the `trading-api:dev`, `trading-worker:dev`, and `trading-fetcher:dev` images to a single archive and upload it as a workflow artifact.
- Reuse a local composite action to download the archive and load it in the image-scan and application-test jobs.
- Keep the archive filename and artifact name shared through workflow-level variables and composite-action inputs.