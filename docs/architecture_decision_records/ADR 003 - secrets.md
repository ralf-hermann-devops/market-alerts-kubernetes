# ADR 003: Sealed Secrets for Kubernetes Secrets

## Context

Application credentials and other sensitive configuration must not be stored directly in Git. Kubernetes Secrets are only Base64-encoded by default and are not encrypted in the manifest. Committing plain Kubernetes Secrets to Git would therefore expose credentials to anyone with repository access.

The local Docker Compose and CI Job "Kubernetes local deployment test" configuration contains development passwords because the images need temporary credentials to provision and run the services during local testing. These are throwaway values for local development and are not production credentials. For a late deployment in production in the cloud and proper testing of the whole system a safe solution is required.


## Decision

Use Sealed Secrets for Kubernetes secrets from the start.

- Sensitive values are encrypted before being committed to Git.
- The Kubernetes cluster decrypts the values at deployment time using the Sealed Secrets controller.

## Rationale

Sealed Secrets provide a simple GitOps-compatible workflow while keeping encrypted secret manifests alongside the application configuration.

This is preferable to relying on standard Kubernetes Secrets in Git, even when the repository is private. It establishes the correct separation between configuration that belongs in version control and credentials that should remain protected.

For environments that already provide a dedicated secrets manager, such as AWS Secrets Manager, External Secrets can be considered instead.

## Trade-offs

- Sealed Secrets introduce a controller and key management requirement in the cluster.

- External Secrets Managers add complexity and relly on a connection to Cloud ressources

## Implementation

### Early local testing with docker
Local development uses temporary credentials in `docker-compose.yml`:

```yaml
REDIS_PASSWORD: redis-dev-password
POSTGRES_PASSWORD: password
```

These credentials are intentionally disposable and exist only to support local image and integration testing.

### Deployment in Kubernetes

The sealed manifest is applied with the selected Kustomize overlay. A bootstrap script will be created to securely provide the cluster with the required secrets using Sealed Secrets.

## Further Considerations

- Application logs must never print raw secrets, tokens, connection strings, database credentials, or request payloads that include sensitive values. Logging and alerting should use redaction and structured sanitization by default.
- Secret handling should be reviewed with the logging and observability setup, because logs, traces, and crash reports can unintentionally become a second place where credentials are exposed.

## When to Revisit This Decision

Consider External Secrets when a managed secrets service such as AWS Secrets Manager becomes the central source of truth across multiple environments or applications.
