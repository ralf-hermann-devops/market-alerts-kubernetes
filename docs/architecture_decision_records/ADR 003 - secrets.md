# ADR 003: Sealed Secrets for Kubernetes Secrets

## Context

Application credentials and other sensitive configuration must not be stored directly in Git. Kubernetes Secrets are only Base64-encoded by default and are not encrypted in the manifest. Committing plain Kubernetes Secrets to Git would therefore expose credentials to anyone with repository access.

The local Docker Compose and CI Job "Kubernetes local deployment test" configuration contains development passwords because the images need temporary credentials to provision and run the services during local testing. These are throwaway values for local development and are not production credentials. For a late deployment in production in the cloud and proper testing of the whole system a safe solution is required.


## Decision

Use Sealed Secrets for Kubernetes secrets from the start.
- Sealed Secrets are selected for easily GitOps-managed manifests without requiring a separate secrets platform.
- Sensitive values are encrypted before being committed to Git. The Sealed Secrets controller in the cluster decrypts the values at deployment time.

<br/>

> [!NOTE]
> Sealed Secrets require access to the matching sealing key to decrypt manifests. Losing it can prevent recovery of the encrypted values.

<br/>


## Rationale






| Consideration | Plaintext Secret | Sealed Secret | Secret Store CSI Driver | HashiCorp Vault |
| ------------ | ----------- | ------------ | ---------------------- | --------------- |
| Safe to store in Git | ❌ **No**<br/>Base64 is not encryption. | ✅ **Yes**<br/>Values are encrypted before commit. | ✅ **Yes**<br/>Secret values remain in the external store. | ✅ **Yes**<br/>Secret values remain in Vault. |
| GitOps workflow | ⚠️ **Poor**<br/>fit; committing values exposes them to repository readers. | ✅ **Strong**<br/>fit; encrypted manifests can be versioned and deployed with the application configuration. | ✅ **Good**<br/>fit; Git can hold references and CSI configuration, not the secret values. | ✅ **Good**<br/>fit; Git can hold Vault integration configuration, not the secret values. |
| Setup requirements | ✅ **None**<br/>beyond Kubernetes. | ⚠️ **Install**<br/>the controller and provision its sealing key. | ⚠️ **Higher**<br/> Configure an external store and a compatible CSI provider. | ⚠️ **Highest**<br/> Set up a Vault service & configure Kubernetes authentication, and access policies. |
| Cloud integration | ❌ **Not**<br/>applicable. | ✅ **Cloud-provider**<br/>agnostic. | ⚠️ **Depends**<br/>on the provider; commonly cloud-specific. | ✅ **Cloud-provider**<br/>agnostic. |
| Operational complexity | ✅ **Low**<br/>but insecure. | ⚠️ **Moderate**<br/>maintain controller availability and sealing-key backups/rotation. | ⚠️ **Higher**<br/>maintain provider availability and runtime secret synchronization. | ⚠️ **Higher**<br/>operate Vault and maintain its availability and upgrades. |
| Unique advantage | **Native**<br/>Supported directly by Kubernetes. | **GitOps**<br/>Encrypted manifests can be versioned alongside application configuration. | **Rotation** <br/> Mounted values can refresh automatically<br/><br/> **Reduced attack surface** <br/> Secret values aren't stored in an additional `Secret` Object but injected directly into pods | **Dynamic**<br/>Can issue short-lived credentials on demand.<br/><br/> **Policies**<br/>Fine-grained access policies control which identities can access secrets. |
| Best fit | ⚠️ <br/> Temporary local or throwaway test credentials. | 1️⃣<br/> Kubernetes deployments that need encrypted, GitOps-managed secret manifests without a separate secrets platform. | 2️⃣<br/> Environments already using a managed external secrets service. | Organizations needing centralized, portable secret management or dynamic credentials. |

---

<br/>

## Trade-offs

- If regular secret rotation and native AWS integration are needed, the Secrets Store CSI Driver can retrieve secrets from AWS Secrets Manager and refresh mounted values when the source changes. Applications have to support get secrets from mounte files and refresh them on change.
- HashiCorp Vault offers many capabilities, including dynamic credentials and portability across cloud providers, but its broader feature set and operational requirements are beyond the scope of this project.



## Implementation

### Early local testing with docker
Local development uses temporary credentials in `docker-compose.yml`:

```yaml
REDIS_PASSWORD: redis-dev-password
POSTGRES_PASSWORD: password
```

These credentials are intentionally disposable and exist only to support local image and integration testing.

### Deployment in Kubernetes

The bootstrap script installs configured external Helm charts, installs the selected overlay's Sealed Secrets controller, generates the encrypted SealedSecret manifest, and applies the selected Kustomize overlay. Secret generation happens only after the controller is ready so its public certificate is available to `kubeseal`.

<br/>

## Further Considerations

- Application logs must never print raw secrets, tokens, connection strings, database credentials, or request payloads that include sensitive values. Logging and alerting should use redaction and structured sanitization by default.
- Secret handling should be reviewed with the logging and observability setup, because logs, traces, and crash reports can unintentionally become a second place where credentials are exposed.

## When to Revisit This Decision

For the planned AWS cloud deployment, consider replacing Sealed Secrets with the Secrets Store CSI Driver integrated with AWS Secrets Manager. Keep Sealed Secrets as the secret-management approach for on-premises deployments.
