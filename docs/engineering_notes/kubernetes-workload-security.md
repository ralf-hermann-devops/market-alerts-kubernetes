# Kubernetes workload security baseline

The current hardening settings intentionally target the project-owned Python containers. Redis and PostgreSQL use upstream images with data and startup behavior that need separate validation before applying a read-only root filesystem or overriding their runtime users.

The API, worker, and fetcher pods use these security controls:

- **Run as UID/GID `10001` (non-root):** limits damage if an application process is compromised; it cannot use root privileges inside the container.
- **`RuntimeDefault` seccomp profile:** filters system calls the runtime considers unnecessary, reducing the kernel attack surface available to a compromised process.
- **Privilege escalation disabled:** prevents a process from gaining additional privileges through mechanisms such as setuid binaries.
- **All Linux capabilities dropped:** removes extra kernel privileges that could enable actions beyond ordinary application work.
- **Read-only root filesystem:** prevents an attacker or compromised process from modifying the container image’s files or persisting changes there.
- **Size-limited writable `/tmp`:** permits temporary-file writes without making the root filesystem writable, while limiting temporary storage exhaustion. The fetcher uses `/tmp` as `HOME` for runtime caches. Currently none of the apps write to disk but it might come in handy later on

The API, worker, fetcher, Redis, and PostgreSQL each use a dedicated ServiceAccount with token automount disabled. The separate identities avoid sharing one default identity and allow permissions to be scoped independently. Disabling token automount prevents workloads from obtaining an unnecessary Kubernetes API credential. None of these workloads calls the Kubernetes API, so no Role or RoleBinding is needed.

