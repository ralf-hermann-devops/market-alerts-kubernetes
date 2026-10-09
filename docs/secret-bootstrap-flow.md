# Kubernetes secret bootstrap and deployment

The bootstrap script installs the supporting infrastructure first, then creates the encrypted secret manifest and applies the selected application overlay. The diagram shows where secret values are handled and how workloads receive the resulting Kubernetes Secret.

```mermaid
flowchart TB
    user["User: select overlay<br/>kubectl points to target cluster"]

    subgraph bootstrap["1. Install prerequisites in target cluster"]
        direction LR
        infra["Apply KEDA and<br/>Sealed Secrets controller"]
        crds["Wait for both<br/>CRDs to be established"]
        controller["Wait for controller<br/>to become ready"]
        infra --> crds --> controller
    end

    subgraph prepare["2. Create encrypted secret manifest on user's machine"]
        direction LR
        inputs["Enter webhook, Redis,<br/>and PostgreSQL secrets"]
        cert["Fetch controller's<br/>public certificate"]
        seal["Create temporary Secret YAML<br/>and seal with strict scope"]
        manifest[("Encrypted SealedSecret<br/>manifest")]
        inputs --> seal
        cert --> seal --> manifest
    end

    subgraph deploy["3. Apply application resources to target cluster"]
        direction LR
        apply["Apply selected<br/>Kustomize overlay"]
        reconcile["Controller decrypts<br/>the SealedSecret"]
        secret[("Kubernetes Secret<br/>trading-alerts-secrets")]
        workloads["Workloads read keys<br/>through secretKeyRef"]
        apply --> reconcile --> secret --> workloads
    end

    user --> infra
    controller --> cert
    manifest --> apply

    classDef sensitive fill:#fff2cc,stroke:#b8860b,color:#222
    class inputs,seal sensitive
```

Only the encrypted `SealedSecret` manifest is suitable for storing in Git; do not commit plaintext values or the temporary Secret YAML. The Sealed Secrets public certificate is used to encrypt values and is not sufficient to decrypt them. Decryption uses the controller's private key in the target cluster.

The bootstrap script selects the overlay before installing infrastructure, waits for both CRDs and for the controller deployment to become ready, generates the manifest, then applies the overlay. The default interactive mode prompts for values without echoing them. Non-interactive use requires all three values; avoid passing real credentials as command-line arguments because they may be exposed in shell history or process listings.
