# Development Challenges and Debugging Notes

This document records problems encountered while developing and deploying the
Trading Alerts application, how they were investigated, and what resolved them.


## 1. Testing the full service flow and locating failures

API unit tests alone could not verify that a webhook traveled through Redis,
was consumed by the worker, and was persisted in PostgreSQL, while testing only
the full stack made it difficult to isolate a failing service boundary.

**Solution:** Test at multiple levels. API TestClient tests cover health
checks, valid and invalid webhook secrets, and logging behavior. Docker smoke
tests exercise the API and worker in containers. The API-to-worker integration
test sends a webhook and verifies that the worker writes the expected event to
PostgreSQL.

The container tests use their own Compose project names and clean up containers
and volumes afterward, helping avoid interference from earlier runs. When an
integration test fails, inspect API and worker logs and check Redis/PostgreSQL
readiness, then use the service boundaries in the first section to narrow down
the cause.


## 2. Inconsistent configuration and communication between microservices

Duplicated and inconsistent service configuration made it difficult to connect
the API, worker, Redis, and PostgreSQL reliably, and mismatches in credentials
or message formats could disrupt communication.

**Solution:** Set `REDIS_HOST` to the Compose DNS hostname `redis` and
`POSTGRES_HOST` to `postgres`, with their ports configured separately. These
are host-and-port settings, not full Redis or PostgreSQL connection URLs. Use
matching credentials and environment variables on both sides of each
connection. Keep shared Redis and PostgreSQL settings in Compose environment
anchors and reuse those anchors for services that need them, rather than
maintaining separate copies. Keep message production and consumption in sync
by checking the format written to the Redis stream against what the worker
reads.

**Debugging tip:** Trace the path one boundary at a time: verify webhook
authentication at the API, API-to-Redis and worker-to-Redis connectivity, the
stream message format, and finally worker-to-PostgreSQL connectivity and schema
compatibility.

## 3. Installing Kubernetes infrastructure before custom resources

Applying application resources before their custom resource definitions (CRDs)
were established could fail because Kubernetes did not yet recognize kinds
such as KEDA's `ScaledObject`.

**Solution:** Split bootstrap into stages. First install supporting
infrastructure, including KEDA and Sealed Secrets, and wait for their CRDs to
be established. Only then apply application resources that use those custom
resource kinds.

**Debugging tip:** If Kubernetes reports an unknown resource kind, check that
the corresponding CRD exists and is established before investigating the
application resource.


## 4. Generating the SealedSecret before applying the application overlay

The application Kustomization will fail to build if it references the generated
SealedSecret YAML before that file exists. Leaving the manifest out until after
deploying the application avoids the missing-file error, but workloads that
need the Secret may fail to start until it is created and might night to be
rolled out again.

**Solution:** After installing the Sealed Secrets CRD and controller, 
wait for the controller deployment in `kube-system` to become ready.
The controller has to be up to hand out its public key which is used for
generating a Sealed Secret yaml definition.
Then generate the SealedSecret manifest before applying the application
overlay that references it. The generation script prompts for values without
echoing them, fetches the controller's public certificate for `kubeseal`, and
writes the encrypted manifest rather than a plain Secret.

**Debugging tip:** For a Kustomize missing-file error, check that the generated
manifest exists at the path in the Kustomization. If a workload cannot start
because a Secret is missing, check whether the SealedSecret was created and
reconciled by the controller, and confirm `kubectl` targets the intended
cluster.

