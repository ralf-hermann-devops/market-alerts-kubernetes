# ADR 002: Postgres as a StatefulSet


## Problem

The workers and the fetcher store their results in a database. I need to decide how to run Postgres.

## Decision

For testing the application I will run Postgres as a simple container and for the first Kubernetes tests as StatefulSet in the cluster, with a persistent volume and a headless service.

## Rationale

- I want to start with a basic implementation for local testing and later simple operation using core Kubernetes concepts.
- My first k8s tests will runs locally in Minikube or Kind, without a cloud account and without cost.
- I have full control and can see what happens under the hood.

## Trade-offs

- For proper operation I will have to build backups, updates, replication and failover myself. With a managed service like RDS, the provider handles this.
- A database operator like CloudNativePG would automate this and is closer to what is used in production. This is no option for the start using docker and local python though.
- A single pod will be a single point of failure.

## Implementation

- Simple container image with docker for early tests
- StatefulSet with one pod and a persistent volume.
- Headless service.
- Credentials from a Kubernetes Secret.

## When to Revisit This Decision

- When the application and remaining tests mature and the kubernetes cluster is otherwise build
- If the data becomes important and I can no longer afford to lose it,
- if I run the project on AWS. Then I will use RDS or an operator.