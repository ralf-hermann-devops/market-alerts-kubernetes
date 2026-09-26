# ADR 004: Kustomize for Kubernetes configuration

## Context

This project needs a straightforward way to manage Kubernetes configuration across a small number of environments. At this scale, we only need two environments: development and production, with small differences between them.

## Decision

Use Kustomize to manage Kubernetes manifests. Keep the shared configuration in a base and use overlays for environment-specific adjustments.

## Rationale

- Kustomize keeps the Kubernetes resources as plain YAML.
- Shared Kubernetes resources can be maintained once and customized through development and production overlays.
- Makes environment differences visible as small changes in overlays. This simplicity makes the configuration easier to read and maintain for the project's scale and requirements.

## Trade-offs
- Helm offers more features and flexibility, but its templating can make the rendered configuration harder to read and reason about. Those capabilities are not currently needed
- With only a few small environment-specific adjustments, Kustomize overlays provide a simpler fit.


## Implementation
- Separation of kubernetes yaml files into base and overlay
- Helm will still be used to install external charts like monitoring into the cluster

## When to Revisit This Decision
- If the project later needs more complex packaging, parameterization, or release management, Helm can be reconsidered.