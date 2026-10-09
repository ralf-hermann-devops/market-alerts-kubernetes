#!/usr/bin/env python3

import argparse

from cluster_image_loading import (
    IMAGES,
    build_images,
    output,
    run,
    run_with_error_handling,
    prompt_for_runs_cluster_name,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build application images and load them into selected or new kind clusters."
    )
    parser.add_argument(
        "--name",
        help="Name to use for a new cluster (prompts if omitted)",
    )
    args = parser.parse_args()

    def load() -> None:
        clusters = [
            cluster.strip()
            for cluster in output(["kind", "get", "clusters"]).splitlines()
            if cluster.strip()
        ]
        selected_clusters, create_cluster = prompt_for_runs_cluster_name("kind", clusters, args.name)
        build_images()
        for cluster in selected_clusters:
            if create_cluster:
                run(["kind", "create", "cluster", "--name", cluster])
            run(["kind", "load", "docker-image", *IMAGES, "--name", cluster])
            print(f"Images loaded successfully into the kind cluster '{cluster}'.")

    return run_with_error_handling(load)


if __name__ == "__main__":
    raise SystemExit(main())
