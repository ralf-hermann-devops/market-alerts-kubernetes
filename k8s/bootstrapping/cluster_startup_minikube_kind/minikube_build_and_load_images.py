#!/usr/bin/env python3

import argparse
import json

from cluster_image_loading import (
    IMAGES,
    build_images,
    output,
    run,
    run_with_error_handling,
    prompt_for_runs_cluster_name,
)


def get_profiles() -> list[str]:
    """Return valid Minikube profile names, raising TypeError for an invalid schema."""
    profiles = json.loads(output(["minikube", "profile", "list", "-o", "json"]))
    if not isinstance(profiles, dict) or not isinstance(profiles.get("valid"), list):
        raise TypeError("Unexpected output from 'minikube profile list -o json'.")

    names = []
    for profile in profiles["valid"]:
        if not isinstance(profile, dict) or not isinstance(profile.get("Name"), str):
            raise TypeError("A Minikube profile has no valid name.")
        names.append(profile["Name"])
    return names


def main() -> int:
    """Parse CLI options, build and load Minikube images, and return an exit status."""
    parser = argparse.ArgumentParser(
        description="Build application images and load them into selected or new Minikube profiles."
    )
    parser.add_argument(
        "--name",
        help="Name to use for a new profile (prompts if omitted)",
    )
    args = parser.parse_args()

    def load() -> None:
        """Select profiles, build images, and start each profile before loading images."""
        profiles = get_profiles()
        selected_profiles, _ = prompt_for_runs_cluster_name("Minikube", profiles, args.name)
        build_images()
        for profile in selected_profiles:
            run(["minikube", "start", "--profile", profile])
            for image in IMAGES:
                run(["minikube", "--profile", profile, "image", "load", image])
            run(["minikube", "--profile", profile, "image", "list"])
            print(f"Images loaded successfully into the Minikube profile '{profile}'.")

    return run_with_error_handling(load)


if __name__ == "__main__":
    raise SystemExit(main())
