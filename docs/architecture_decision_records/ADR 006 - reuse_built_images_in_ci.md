# ADR 006: Build and reuse service images in CI

## Context

The image-scan matrix and Docker-based application tests each need the API, worker, and fetcher images. Building images independently in each job keeps jobs self-contained and can make the overall workflow finish sooner because the builds run in parallel. However, it repeats expensive work and increases aggregate runner compute.

## Decision

Build the service images once in a dedicated CI job, save them as a Docker archive, upload the archive as a workflow artifact, and download and load the same images in the scan and test jobs.

## Rationale

As for the current state of the pipeline: quick measurements show that the repeated-build pipeline uses approximately 35 seconds per build across four consumers. That's about 140 seconds of aggregate compute. Building once and then distributing the archive is estimated at about 45 seconds for the build and upload, plus approximately 15 seconds for each of four downloads and loads, or about 105 seconds of aggregate compute.

Reusing one build also ensures that tests and scans operate on the same image artifacts, avoids redundant builds, and makes the CI flow explicit: build, distribute, then validate. The compute savings should become more significant if images become more complex or more jobs need to use them.

## Trade-offs

- Artifact upload, download, and image loading add workflow steps and increase the total pipeline run time (currently from approximately 1 minute 40 seconds to 2 minutes 15)
- Large images can make the archive significantly larger, increasing upload and download time, storage use, and transfer strain. Reassess this approach if artifact transfer becomes a bottleneck.

Important note: All numbers used here are approximate and vary slightly between runs and steps. The expected resource saving is modest for the current images.

## Implementation

- Build `api`, `worker`, and `fetcher` once with Docker Compose.
- Save the `trading-api:dev`, `trading-worker:dev`, and `trading-fetcher:dev` images to one archive and upload it as a short-lived Actions artifact.
- Reuse a local composite action to download the archive and load it in the image-scan and application-test jobs.
- Keep the archive filename and artifact name shared through workflow-level variables and composite-action inputs.