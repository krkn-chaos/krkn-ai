## Krkn-AI Service

This image is used as part of krkn-operator stack to provide results management service.

The image carries the same operator integration-contract label as the runner.
See [compatibility maintenance](../docs/developer_guide.md#maintaining-operator-integration-compatibility)
for its guarantees and when to increment it.

### Building the artifact service image

The artifact service receives authenticated results from operator-managed runs
and stores them beneath `runs/<KrknAIRun UID>/` on its single mounted PVC.
Build and publish it separately from the runner image:

```bash
podman build \
  -f containers/Containerfile.server \
  -t quay.io/krkn-chaos/krkn-ai-service:<tag> \
  .
podman push quay.io/krkn-chaos/krkn-ai-service:<tag>
```

For a local smoke test, mount a writable directory at the service artifact
root and set a non-empty bearer token:

```bash
mkdir -p ./tmp/krkn-ai-artifacts
export KRKNAI_SERVICE_TOKEN="$(openssl rand -hex 32)"

podman run --rm -p 8080:8080 \
  -v ./tmp/krkn-ai-artifacts:/var/lib/krkn-ai:Z \
  -e KRKNAI_SERVICE_TOKEN \
  quay.io/krkn-chaos/krkn-ai-service:<tag>
```

In Kubernetes, the operator chart mounts either
`aiService.storage.existingClaim` or its retained chart-created PVC at
`/var/lib/krkn-ai`. Keep this service private to the operator namespace; its
token is required for every discovery and artifact route.

### Checkpoints and cancellation

Uploads are staged separately from the published snapshot. A commit validates the
uploaded checksums and cross-file result references, writes a complete immutable
revision, then atomically publishes it. Interrupted or invalid uploads therefore
leave the last committed snapshot readable. Terminal `succeeded`, `failed`, and
`cancelled` snapshots cannot be overwritten; deleting the run remains the explicit
way to remove retained artifacts.

`GET /v1/runs/{uid}/results` returns the logical file paths and checksums plus
`committedAt`. Archive readers can pin each file to that snapshot with
`GET /v1/runs/{uid}/files/{path}?sha256=<manifest checksum>`; an unqualified file
read continues to return the latest committed version. Cancellation is finalized
from the runner's explicit completion-marker `outcome`, not inferred from its
numeric exit code.
