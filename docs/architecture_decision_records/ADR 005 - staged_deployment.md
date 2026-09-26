# ADR 005: Staged deployment from Docker to EKS

## Context

The application can be tested locally with Docker Compose and has Kubernetes manifests organized with Kustomize. Moving directly to a cloud cluster would introduce AWS infrastructure concerns before the application and Kubernetes configuration have been validated independently.

## Decision

Build and validate the application in stages: Docker Compose for local container testing, a local Kubernetes cluster for Kubernetes testing, and Amazon EKS when cloud deployment is needed. Keep shared application manifests as portable as practical and isolate environment-specific changes in Kustomize overlays.

## Rationale

- Docker Compose verifies image builds, configuration, and service communication without requiring Kubernetes.
- A local cluster verifies Kubernetes resources and their interactions without cloud costs or dependencies.
- Once both stages work, failures introduced in EKS can be investigated as cloud infrastructure or integration issues.
- Reusing shared manifests makes the move to EKS a controlled migration rather than a separate deployment design.

## Trade-offs

- Local Kubernetes does not reproduce all EKS behavior, including AWS networking, IAM, and cloud storage integrations.
- Maintaining local and cloud configurations requires care to prevent overlays from drifting.
- The staged approach adds validation steps, but helps isolate problems and avoids making everyday development depend on AWS.

## Implementation

- Use the existing Docker Compose setup for local image and service testing. Its development credentials are disposable and must not be used in shared or production environments.
- Use a local Kubernetes cluster such as kind or Minikube to validate manifests, services, configuration, storage, health checks, and resource settings.
- When moving to EKS, keep common resources in the Kustomize base and add an EKS-specific overlay for cloud integrations such as load balancing, storage, IAM, and External Secrets.
- Publish deployable images to a container registry such as Amazon ECR for EKS.

## Transition Criteria
- Start with local tests and Docker Compose
- Move from Docker Compose to a local Kubernetes cluster when images start reliably and the application works with its dependencies in containers.
- Move from local Kubernetes to EKS when the application and manifests work locally and are ready for testing AWS integrations. Reassess the shared base and overlays EKS-specific requirements divert from local Kubernetes configurations

## CI/CD
- Introduce CI early, while development is still local. Run the existing automated tests and Docker Compose image builds on pull requests so changes are checked consistently before merging.
- Add CD when EKS and its infrastructure, registry, and secret access are ready. Start with a gated or manually approved deployment; automate promotion further once deployments are repeatable and rollback procedures are understood.
