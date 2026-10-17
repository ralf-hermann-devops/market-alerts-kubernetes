# Local testing

## Table of contents

- [Application unit tests](#application-unit-tests)
- [Docker smoke and integration tests](#docker-smoke-and-integration-tests)
- [Kubernetes manifest and cluster tests](#kubernetes-manifest-and-cluster-tests)
  - [Skip if not testing Kubernetes manifests](#skip-if-not-testing-kubernetes-manifests)
  - [Validating manifests](#validating-manifests)
    - [Scan individual source manifests](#scan-individual-source-manifests)
    - [Install Helm charts and apply the sealed-secrets controller](#install-helm-charts-and-apply-the-sealed-secrets-controller)
    - [Build, scan and apply the project manifests](#build-scan-and-apply-the-project-manifests)
  - [Run tests on the active cluster](#run-tests-on-the-active-cluster)
- [Other checks](#other-checks)
  - [Run the lint check](#run-the-lint-check)
  - [Run the dependency audits](#run-the-dependency-audits)
  - [Build and scan images](#build-and-scan-images)

<br/>

---

<br/>

## Application unit tests

Install the API test dependencies, then run the unit tests. These tests use a fake Redis client and do not require Docker or a running Redis instance:

```bash
python -m pip install -r services/api/requirements.txt
python -m pytest services/api/tests/test_testclient_api.py
```

## Docker smoke and integration tests

Start Docker Desktop or the Docker daemon first. The scripts build images as needed, start temporary Compose projects, run their checks, and remove their containers and volumes afterward:

```bash
python services/api/tests/docker_api_smoke_test.py
python services/worker/tests/docker_worker_smoke_test.py
python services/tests/docker_api_worker_integration_test.py
```

The API smoke test checks health, readiness, and valid and invalid webhooks. The worker smoke test checks that queued Redis events are persisted to PostgreSQL. The integration test submits a webhook to the API and verifies that the worker persists it. To reuse images you have already built, set `COMPOSE_NO_REBUILD_IN_TESTS=1` before running the scripts.

## Kubernetes manifest and cluster tests

### Skip if not testing Kubernetes manifests
You can deploy the infrastructure and selected application overlay directly with the bootstrap script described in the [Kubernetes section of the README](../../readme.md#kubernetes-in-minikube-or-kind).

### Validating manifests
CI uses Kubeconform to check Kubernetes resource schemas: required fields, field values and types, and (with strict mode) unknown fields and duplicate YAML keys. Install Kubeconform 0.8.0, `kubectl`, and Helm 3.17 or newer. Helm is required to install the configured charts; `--take-ownership` lets KEDA adopt resources from earlier Kustomize-based installs. From the repository root, run the following in Bash, Git Bash, or WSL. See the [Kubernetes manifest validation note](../engineering_notes/kubernetes-manifest-validation.md) for details.

Set the Kubeconform arguments and a regex to exclude patch files and Kustomization manifests from the scan:
```bash
KUBECONFORM_ARGS=(
  -summary
  -output pretty
  -skip CustomResourceDefinition
  -schema-location default
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/refs/heads/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
  -strict
)
PATCH_EXCLUSIONS='(?i)(^|[\\/])([^\\/]*patch[^\\/]*|kustomization\.yaml)$'
```

#### Scan individual source manifests.
```bash
kubeconform "${KUBECONFORM_ARGS[@]}" -ignore-filename-pattern "$PATCH_EXCLUSIONS" k8s/manifests/base
kubeconform "${KUBECONFORM_ARGS[@]}" -ignore-filename-pattern "$PATCH_EXCLUSIONS" k8s/manifests/overlays/on-premise
```

<br/>

#### Install Helm charts and apply the sealed-secrets controller

Before applying the application overlay, install KEDA and kube-prometheus-stack so their custom resource definitions exist. The stack installs Prometheus, Grafana, and Kubernetes exporters with the chart's default settings. The bootstrap script performs these steps automatically. To install the configured Helm charts separately:

```bash
python k8s/bootstrapping/helm_charts_setup/install_helm_charts.py
```

Each chart can optionally set `values_file` in `install_helm_charts.py`; when set, that path is passed to Helm with `--values`. Paths are interpreted relative to the working directory used to run the installer. For dashboard access and monitoring queries, see the [Kubernetes monitoring guide](./kubernetes-monitoring.md).

Install the on-premise Sealed Secrets controller:

```bash
kubectl kustomize k8s/manifests/overlays/on-premise/sealed_secrets_install > sealed_secrets_install.yaml
kubeconform "${KUBECONFORM_ARGS[@]}" sealed_secrets_install.yaml
kubectl apply -f sealed_secrets_install.yaml
```

<br/>

Wait for the SealedSecrets CRD and controller to be ready. More about that in the [secret-bootstrap-flow guide](./secret-bootstrap-flow.md).

```bash
kubectl wait --for=condition=Established crd/sealedsecrets.bitnami.com --timeout=120s
kubectl rollout status deployment/sealed-secrets-controller --namespace kube-system --timeout=120s
```

<br/>

Once the Sealed Secrets controller is ready, generate a SealedSecret using disposable test credentials. This writes the manifest required by the on-premise overlay:

```bash
python k8s/bootstrapping/create_sealed_secret.py --webhook-secret test-webhook-secret --redis-password test-redis-password --postgres-password test-postgres-password --non-interactive
```
Or use the interactive prompt to enter your own secret values:
```bash
python k8s/bootstrapping/create_sealed_secret.py
```

<br/>

#### Build, scan and apply the project manifests

Now validate the base manifests individually to catch errors in the base configuration. Then do the same for the overlay. Read more about why that is done like that [here](../engineering_notes/kubernetes-manifest-validation.md).

```bash
kubectl kustomize k8s/manifests/base > base.yaml
kubeconform "${KUBECONFORM_ARGS[@]}" base.yaml
kubectl kustomize k8s/manifests/overlays/on-premise > on-premise.yaml
kubeconform "${KUBECONFORM_ARGS[@]}" on-premise.yaml
kubectl apply -f on-premise.yaml
```

## Run tests on the active cluster

To test against a running local minikube or kind cluster, make sure `kubectl` targets that cluster and the required tools are installed (`kubectl`, `kubeseal`, and Helm). Use the appropriate image build-and-load helper and bootstrap steps in the [Kubernetes section of the README](../../readme.md#kubernetes-in-minikube-or-kind). After deploying the `on-premise` overlay, run the readiness check below.

The readiness check confirms that all workload controllers can start and waits for the API, worker, Redis, and PostgreSQL workloads to become ready. It requires the `on-premise` overlay and the `trading-alerts` namespace to be deployed.

```bash
python k8s/tests/smoke_tests/workload_controllers_started/run.py
```

Once the readiness check succeeds and the API, worker, Redis, and PostgreSQL are ready, run the passthrough test:

```bash
python k8s/tests/smoke_tests/simple_passthrough/run.py
```

This creates a Kubernetes Job that sends a webhook through the API and checks that the worker stores the alert in PostgreSQL. The full path depends on the `api` service, the worker consuming the alert, Redis carrying it between the API and worker, and PostgreSQL storing it.


## Other checks

The CI pipeline also runs Ruff, audits each service's dependencies, builds the service images, and scans them with Trivy. Run these commands from the repository root.

Install Ruff and the dependency-audit tools in your Python environment:

```bash
python -m pip install ruff pip-audit pipdeptree
```

### Run the lint check:
```bash
ruff check --isolated services
```
### Run the dependency audits:
For each service (`api`, `worker`, and `fetcher`), install its requirements and run the same dependency checks used in CI. For example, for the API:

```bash
python -m pip install -r services/api/requirements.txt
pipdeptree --warn silence
pip-audit -r services/api/requirements.txt
```

Replace `api` with `worker` or `fetcher` to audit the other services. CI runs each service audit in a separate environment.

### Build and Scan Images

Build the images locally with Docker Compose, then scan each image with Trivy. Install Trivy first if it is not already available:

```bash
docker compose -f Dockercompose.yaml build --pull api worker fetcher
```
```bash
trivy image --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 --skip-files /usr/local/lib/python3.14/site-packages/pip/_vendor/bom.cdx.json trading-api:dev
```
```bash
trivy image --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 --skip-files /usr/local/lib/python3.14/site-packages/pip/_vendor/bom.cdx.json trading-worker:dev
```
```bash
trivy image --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 --skip-files /usr/local/lib/python3.14/site-packages/pip/_vendor/bom.cdx.json trading-fetcher:dev
```

The Kubernetes manifest and cluster checks are covered in the sections below. For details about CI's individual and assembled-manifest kubeconform scans, see the [Kubernetes manifest validation note](../engineering_notes/kubernetes-manifest-validation.md).

To test the externally routed HTTPS path, including the Traefik Ingress, local
CA certificate, TLS hostname, and webhook authentication, run:

```bash
python k8s/tests/smoke_tests/https_webhook/run.py
```

This temporarily forwards Traefik's HTTPS service port to localhost and sends
the request with `alerts.example.invalid` as both the TLS server name and HTTP
host. The port-forward is terminated when the test completes.
