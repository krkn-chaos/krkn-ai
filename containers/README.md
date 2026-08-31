# Krkn-AI Container Usage Guide

Krkn-AI can be run inside containers, which simplifies integration with continuous testing workflows.

## Container Image

A pre-built container image is available on Quay.io:

```bash
podman pull quay.io/krkn-chaos/krkn-ai:latest
```

All examples in this document use the `quay.io/krkn-chaos/krkn-ai:latest` image by default.

### Building Manually

If you prefer to build the container image yourself:

```bash
# Run this command from the root directory
podman build -t krkn-ai:latest -f containers/Containerfile .
```

> **Note:** When using a locally built image, replace `quay.io/krkn-chaos/krkn-ai:latest` with `krkn-ai:latest` in the examples below.

### Dedicated operator image

The operator runner does not invoke a local container runtime. Build the
dedicated image to avoid shipping Podman, `krknctl`, or `oc` in the
orchestrator image:

```bash
podman build \
  -f containers/Containerfile.operator \
  -t quay.io/<org>/krkn-ai-operator:mvp \
  .
podman push quay.io/<org>/krkn-ai-operator:mvp
```

`Containerfile.operator` uses Python 3.12, the locked `uv` environment, and
the existing `containers/entrypoint.sh`. It is intended for `MODE=run` with
`RUNNER_TYPE=operator`; discovery mode and the local HUB/CLI runners belong
to the full `Containerfile` image.

### Manual operator execution

Manual execution can run from the host or from any container that has access
to the Kubernetes API. The target cluster must already have the
`krkn-operator` `KrknScenarioRun` CRD and the caller must be allowed to
create, read, and delete `KrknScenarioRun` objects.

Set the operator-runner context:

```bash
export KUBECONFIG=/path/to/kubeconfig
export KRKNAI_NAMESPACE=krkn-operator
export KRKNAI_RUN_NAME=manual-run
export KRKNAI_RUN_UID=$(uuidgen)
export KRKNAI_TARGET_REQUEST_ID=self
export KRKNAI_PROVIDER=krkn-operator
export KRKNAI_CLUSTER=self
export KRKNAI_SCENARIO_MAX_RETRIES=0
```

Run directly from a source checkout:

```bash
uv run krkn_ai run \
  --config ./tmp/krkn-ai.yaml \
  --kubeconfig "$KUBECONFIG" \
  --output ./tmp/operator-results \
  --runner-type operator
```

The executor first tries in-cluster authentication and falls back to the
kubeconfig supplied to `--kubeconfig`, so the same command works inside or
outside Kubernetes. Each generated child CR is labeled
`krkn.dev/ai-run=manual-run`. Because this example uses a generated UID
without a parent `KrknAIRun`, delete the child resources explicitly after
the run.

### Run the dedicated image manually

Mount the config and kubeconfig into the paths used by the image. This image
does not require `--privileged`, a Podman socket, or nested containers:

```bash
mkdir -p ./tmp/operator-results
podman run --rm \
  -v ./tmp:/input:Z \
  -v ./tmp/operator-results:/output:Z \
  -e MODE=run \
  -e CONFIG_FILE=/input/krkn-ai.yaml \
  -e KUBECONFIG=/input/kubeconfig.yaml \
  -e KRKNAI_NAMESPACE=krkn-operator \
  -e KRKNAI_RUN_NAME=manual-run \
  -e KRKNAI_RUN_UID="$(uuidgen)" \
  -e KRKNAI_TARGET_REQUEST_ID=self \
  -e KRKNAI_PROVIDER=krkn-operator \
  -e KRKNAI_CLUSTER=self \
  -e KRKNAI_SCENARIO_MAX_RETRIES=0 \
  -e VERBOSE=2 \
  quay.io/<org>/krkn-ai-operator:mvp
```

The container reads the kubeconfig using the Kubernetes Python client and
creates the scenario pods through `krkn-operator`; it does not run the
scenario image itself.

### Operator image in a `KrknAIRun`

For the controller-managed workflow, set the operator chart's
`images.aiOrchestrator.image` value to the dedicated image:

```bash
helm upgrade --install krkn-operator /path/to/krkn-operator/charts/krkn-operator \
  -n krkn-operator --create-namespace \
  --set images.aiOrchestrator.image=quay.io/<org>/krkn-ai-operator:mvp
```

The controller mounts `krkn-ai.yaml` and the target kubeconfig, sets
`RUNNER_TYPE=operator`, and supplies the `KRKNAI_*` variables automatically.
Use the `KrknAIRun` and target Secret procedure in
[`../hack/test.md`](../hack/test.md) for a complete cluster test.

### Configuring krknctl defaults from a ConfigMap

The operator's scenario controller normally uses the embedded krknctl
defaults. A namespace-local ConfigMap can override them for registry and
kubeconfig defaults. Store JSON matching `krknctl/pkg/config.Config` under the
`config.json` key:

```bash
kubectl -n krkn-operator create configmap krknctl-config \
  --from-file=config.json=/path/to/krknctl-config.json \
  --dry-run=client -o yaml | kubectl apply -f -
```

Install or upgrade the operator with:

```bash
helm upgrade --install krkn-operator /path/to/krkn-operator/charts/krkn-operator \
  -n krkn-operator --create-namespace \
  --set krknctl.configMapName=krknctl-config \
  --set krknctl.configMapKey=config.json
```

The manager reads the ConfigMap when it creates each scenario pod. If
`krknctl.configMapName` is empty, the embedded defaults remain active. A
missing key or invalid JSON fails that scenario creation with an explicit
error.

Do not place registry passwords or tokens in a ConfigMap. Use the existing
registry Secret/image-pull-secret mechanisms for sensitive credentials.

## Running the Container

The container supports two modes controlled by the `MODE` environment variable:

### 1. Discovery Mode

Discovers cluster components and generates a configuration file.

**Usage:**
```bash
# create a folder
mkdir -p ./tmp/container/

# copy kubeconfig to ./tmp/container

# execute discover command
podman run --rm \
  --net="host" \
  -v ./tmp/container:/mount:Z \
  -e MODE="discover" \
  -e KUBECONFIG="/mount/kubeconfig.yaml" \
  -e OUTPUT_DIR="/mount" \
  -e NAMESPACE="robot-shop" \
  -e POD_LABEL="service" \
  -e NODE_LABEL="kubernetes.io/hostname" \
  -e SKIP_POD_NAME="nginx-proxy.*" \
  -e VERBOSE="2" \
  quay.io/krkn-chaos/krkn-ai:latest
```

**Environment Variables (Discovery):**
- `MODE=discover` (required)
- `KUBECONFIG` (required) - Path to kubeconfig file (default: `/input/kubeconfig`)
- `OUTPUT_DIR` (optional) - Output directory (default: `/output`)
- `NAMESPACE` (optional) - Namespace pattern (default: `.*`)
- `POD_LABEL` (optional) - Pod label pattern (default: `.*`)
- `NODE_LABEL` (optional) - Node label pattern (default: `.*`)
- `SKIP_POD_NAME` (optional) - Pod names to skip (comma-separated regex)
- `VERBOSE` (optional) - Verbosity level 0-2 (default: `0`)

### 2. Run Mode

Executes Krkn-AI tests based on a configuration file.

**Usage:**

```bash
podman run --rm \
  --net="host" \
  --privileged \
  -v ./tmp/container:/mount:Z \
  -e MODE=run \
  -e CONFIG_FILE="/mount/krkn-ai.yaml" \
  -e KUBECONFIG="/mount/kubeconfig.yaml" \
  -e OUTPUT_DIR="/mount/result/" \
  -e EXTRA_PARAMS="HOST=${HOST}" \
  -e PROMETHEUS_URL="${PROMETHEUS_URL}" \
  -e PROMETHEUS_TOKEN="${PROMETHEUS_TOKEN}" \
  -e VERBOSE=2 \
  quay.io/krkn-chaos/krkn-ai:latest
```

**Environment Variables (Run):**
- `MODE=run` (required)
- `KUBECONFIG` (required) - Path to kubeconfig file (default: `/input/kubeconfig`)
- `CONFIG_FILE` (required) - Path to krkn-ai config file (default: `/input/krkn-ai.yaml`)
- `OUTPUT_DIR` (optional) - Output directory (default: `/output`)
- `FORMAT` (optional) - Output format: `json` or `yaml` (default: `yaml`)
- `EXTRA_PARAMS` (optional) - Additional parameters in `key=value` format (comma-separated)
- `VERBOSE` (optional) - Verbosity level 0-2 (default: `0`)


## Podman Considerations

The full `Containerfile` image is for the local `krknhub` runner and includes
Podman. Use `Containerfile.operator` for Kubernetes API execution; it does
not require a Podman socket or privileged mode.

### Run without `--privileged` flag

If you do not want to use the `--privileged` flag due to security concerns, you can leverage the host's `fuse-overlayfs` to run a Podman container. Learn more about this approach [here](https://www.redhat.com/en/blog/podman-inside-container).

```bash
mkdir -p ./tmp/container/result && chmod 777 ./tmp/container/result

podman run --rm \
  --net="host" \
  --user podman \
  --device=/dev/fuse --security-opt label=disable \
  -v ./tmp/container:/mount:Z \
  -e MODE=run \
  -e CONFIG_FILE="/mount/krkn-ai.yaml" \
  -e KUBECONFIG="/mount/kubeconfig.yaml" \
  -e OUTPUT_DIR="/mount/result/" \
  -e EXTRA_PARAMS="HOST=${HOST}" \
  -e PROMETHEUS_URL="${PROMETHEUS_URL}" \
  -e PROMETHEUS_TOKEN="${PROMETHEUS_TOKEN}" \
  -e VERBOSE=2 \
  quay.io/krkn-chaos/krkn-ai:latest
```

### Cache KrknHub images

When running Krkn-AI as a Podman container inside another container with FUSE, you can mount a volume to the container's shared storage location to enable downloading and caching of KrknHub images.

```bash
podman volume create mystorage

mkdir -p ./tmp/container/result && chmod 777 ./tmp/container/result

podman run --rm \
  --net="host" \
  --user podman \
  --device=/dev/fuse --security-opt label=disable \
  -v ./tmp/container:/mount:Z \
  -v mystorage:/home/podman/.local/share/containers:rw \
  -e MODE=run \
  -e CONFIG_FILE="/mount/krkn-ai.yaml" \
  -e KUBECONFIG="/mount/kubeconfig.yaml" \
  -e OUTPUT_DIR="/mount/result/" \
  -e EXTRA_PARAMS="HOST=${HOST}" \
  -e PROMETHEUS_URL="${PROMETHEUS_URL}" \
  -e PROMETHEUS_TOKEN="${PROMETHEUS_TOKEN}" \
  -e VERBOSE=2 \
  quay.io/krkn-chaos/krkn-ai:latest
```
