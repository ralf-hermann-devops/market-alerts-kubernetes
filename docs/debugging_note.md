# Development Challenges and Debugging Notes

This document records problems encountered while developing and deploying the Trading Alerts application, how they were investigated, and what resolved them.


## 1. Developing and integrating microservices

Debugging microservices independently is more challenging than monoliths. Unlike a monolith, their components run as separate services with distinct configuration, connectivity, and data-format assumptions. In this application, a webhook passes from the API through Redis to the worker and is then stored in PostgreSQL. A service can work in isolation while a problem at one of these boundaries causes the overall flow to fail.

**Solution:** Test at multiple levels. API TestClient tests cover health checks, valid and invalid webhook secrets, and logging behavior. Docker smoke tests exercise the API and worker in containers, while the API-to-worker integration test verifies that a webhook is consumed and persisted. The container tests use their own Compose project names and clean up containers and volumes afterward, helping avoid interference from earlier runs.

**Debugging takeaway:** Test each service on its own, then verify the cross-service flow. When integration fails, trace the request through each boundary in order—checking logs, readiness, connectivity, and message formats—instead of assuming that individually healthy services make a healthy system.


## 2. Inconsistent configuration and communication between microservices

Duplicated and inconsistent service configuration made it difficult to connect the API, worker, Redis, and PostgreSQL reliably, and mismatches in credentials or message formats could disrupt communication.

**Solution:** Set `REDIS_HOST` to the Compose DNS hostname `redis` and `POSTGRES_HOST` to `postgres`, with their ports configured separately. These are host-and-port settings, not full Redis or PostgreSQL connection URLs. Use matching credentials and environment variables on both sides of each connection. Keep shared Redis and PostgreSQL settings in Compose environment anchors and reuse those anchors for services that need them, rather than maintaining separate copies. Keep message production and consumption in sync by checking the format written to the Redis stream against what the worker reads.

**Debugging takeaway:** Trace the path one boundary at a time: verify webhook authentication at the API, API-to-Redis and worker-to-Redis connectivity, the stream message format, and finally worker-to-PostgreSQL connectivity and schema compatibility.

## 3. Installing Kubernetes infrastructure before custom resources

Applying application resources before their custom resource definitions (CRDs) were established could fail because Kubernetes did not yet recognize kinds such as KEDA's `ScaledObject`.

**Solution:** Split bootstrap into stages. First install supporting infrastructure, including KEDA and Sealed Secrets, and wait for their CRDs to be established. Only then apply application resources that use those custom resource kinds.

**Debugging takeaway:** If Kubernetes reports an unknown resource kind, check that the corresponding CRD exists and is established before investigating the application resource.


## 4. Generating the SealedSecret before applying the application overlay

The application Kustomization will fail to build if it references the generated SealedSecret YAML before that file exists. Leaving the manifest out until after deploying the application avoids the missing-file error, but workloads that need the Secret may fail to start until it is created and might night to be rolled out again.

**Solution:** After installing the Sealed Secrets CRD and controller, wait for the controller deployment in `kube-system` to become ready. The controller has to be up to hand out its public key which is used for generating a Sealed Secret yaml definition. Then generate the SealedSecret manifest before applying the application overlay that references it. The generation script prompts for values without echoing them, fetches the controller's public certificate for `kubeseal`, and writes the encrypted manifest rather than a plain Secret.

**Debugging takeaway:** For a Kustomize missing-file error, check that the generated manifest exists at the path in the Kustomization. If a workload cannot start because a Secret is missing, check whether the SealedSecret was created and reconciled by the controller, and confirm `kubectl` targets the intended cluster.


## 5. Python output buffering in container logs

While testing the API from a temporary Kubernetes Pod, Python `print()` output did not appear in `kubectl logs` until the process exited. This became apparent when writing and running tests that needed to observe output while the container was still running.

**Solution:** Run Python with `-u` or set `PYTHONUNBUFFERED=1` in the container environment to make stdout and stderr unbuffered. Python's standard `logging` handlers normally flush each emitted log record. Because most my application output uses `logging`, the buffering issue only became apparent when tests used `print()` and expected to see output immediately while watching Kubernetes logs. Unbuffered output is therefore most relevant to direct `print()` calls and other buffered writes, rather than ordinary logging.

**Debugging takeaway:** If output appears only after a container exits, check whether it is using buffered stdout before assuming the application is not producing logs.


## 6. Ensuring local Docker tests to fail correctly in CI

The Docker-based test scripts were first used locally, where logs where just looked at and decided whether the test passed. GitHub Actions does not evaluate those messages. It primarily determines success from each command's exit code. As a result, a script could print that a test failed but still exit with status `0`, causing CI to report success.

**Solution:** Make each test outcome affect the process exit status while still allowing the script to print useful diagnostics and clean up its containers. The worker smoke test records whether processing succeeded, prints expected versus actual results and worker logs on failure, performs cleanup in a `finally` block, and returns `1` for failure or `0` for success. Its entry point uses `raise SystemExit(main())` so that returned status reaches the shell. The API-to-worker integration test raises an assertion when the HTTP response or persisted event is incorrect, its `finally` block still tears down the Compose project.

**Debugging takeaway:** A failure message is for people (and supporting AI) to look at and evaluate what happened. A nonzero process exit status is what makes CI fail. Test scripts should report what went wrong and preserve cleanup, then return a failing status or let an exception propagate.
