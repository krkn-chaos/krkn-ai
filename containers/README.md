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
