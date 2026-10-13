## Krkn-AI Service

This image is used as part of krkn-operator stack to provide results management service.

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
