# Local testing

Run the test layers in order: application unit tests, Docker-based tests, then Kubernetes manifest and cluster tests. Run these commands from the repository root.

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
If you do not need to validate the manifests separately, you can deploy the infrastructure and selected application overlay directly with the bootstrap script described in the [Kubernetes section of the README](../readme.md#kubernetes).

### Build Kustomize targets
Before validating the base and dev overlay, deploy the infrastructure components to the cluster. Render the KEDA chart with Helm and apply the infrastructure manifests:

```bash
kubectl kustomize --enable-helm k8s/manifests/infrastructure | kubectl apply -f -
kubectl wait --for=condition=Established crd/scaledobjects.keda.sh --timeout=120s
kubectl wait --for=condition=Established crd/sealedsecrets.bitnami.com --timeout=120s
kubectl rollout status deployment/sealed-secrets-controller --namespace kube-system --timeout=120s
```

Once the Sealed Secrets controller is ready, generate a SealedSecret using disposable test credentials. This writes the manifest required by the base and dev overlay:

```bash
python k8s/bootstrapping/create_sealed_secret.py --webhook-secret test-webhook-secret --redis-password test-redis-password --postgres-password test-postgres-password --non-interactive
```
Or use the interactive prompt to enter your own secret values:
```bash
python k8s/bootstrapping/create_sealed_secret.py
```

Now build each Kustomize target to catch composition and rendering errors (and optionally apply them to the cluster):

```bash
kubectl kustomize k8s/manifests/base    # | kubectl apply -f -
kubectl kustomize k8s/manifests/overlays/dev # | kubectl apply -f -
```

To test against a running local minikube or kind cluster, make sure `kubectl` targets that cluster and the required tools are installed (`kubectl`, `kubeseal`, and Helm). Use the appropriate image build-and-load helper and bootstrap steps in the [Kubernetes section of the README](../readme.md#kubernetes-in-minikube-or-kind). Once the `dev` overlay is deployed and the API, worker, and PostgreSQL are ready, run the Kubernetes smoke test:

## Run tests on the active cluster


```bash
python k8s/tests/smoke_tests/simple_passthrough/run.py
```

This creates a Kubernetes Job that sends a webhook through the API and checks that the worker stores the alert in PostgreSQL. The full path depends on the `api` service, the worker consuming the alert, Redis carrying it between the API and worker, and PostgreSQL storing it. Ensure the `trading-alerts` namespace and all of those application components are deployed and ready before running the test.
