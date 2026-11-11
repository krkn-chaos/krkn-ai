# Developer Guide

This guide explains how to set up a local development environment for Krkn-AI using Minikube.

## Prerequisites

Ensure you have the following installed:
- [kubectl](https://kubernetes.io/docs/tasks/tools/) - Kubernetes CLI
- [jq](https://jqlang.github.io/jq/download/) - JSON processor
- [uv](https://docs.astral.sh/uv/getting-started/installation/) - Python package manager

## 1. Set Up Krkn-AI Repository

```bash
# Option 1: Clone repository
git clone https://github.com/krkn-chaos/krkn-ai.git

# Option 2: Fork the repository to your GitHub profile and clone it
git clone https://github.com/<username>/krkn-ai.git

cd krkn-ai
```

Install the necessary dependencies and Krkn-AI CLI as per the project [README](../README.md).

```bash
# Verify krkn-ai installation
uv run krkn_ai --help
```

## 2. Set Up Minikube

We use [Minikube](https://minikube.sigs.k8s.io/docs/start/) to create a local Kubernetes cluster.

### Install Minikube

**Linux:**
```bash
curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64
```

**macOS (Apple Silicon / Intel):**
```bash
brew install minikube
```

### Create the Cluster

**Linux:**
```bash
minikube start
```

**macOS:**

The recommended driver on macOS is [vfkit](https://github.com/crc-org/vfkit), a lightweight hypervisor that avoids Docker driver limitations (port forwarding, multi-node support). See the [minikube vfkit driver docs](https://minikube.sigs.k8s.io/docs/drivers/vfkit/) for more details.

```bash
brew install vfkit
minikube start --driver=vfkit
```

### Configure Cluster Access

```bash
# Switch to minikube cluster context
kubectl config use-context minikube

# Verify cluster is running
kubectl get pods -A

# Generate kubeconfig for Krkn-AI
kubectl config view \
  --context=minikube \
  --minify \
  --flatten \
  --raw > kubeconfig.yaml
kubectl --kubeconfig=kubeconfig.yaml get pods -A
```

> **Note:** The generated `kubeconfig.yaml` is used by Krkn-AI to connect to your cluster.

## 3. Install Prometheus

Krkn-AI uses Prometheus metrics for fitness evaluation during chaos testing.

### Install Prometheus Operator

[Prometheus Operator](https://prometheus-operator.dev/) simplifies Prometheus management on Kubernetes.

```bash
LATEST=$(curl -s https://api.github.com/repos/prometheus-operator/prometheus-operator/releases/latest | jq -cr .tag_name)
curl -sL https://github.com/prometheus-operator/prometheus-operator/releases/download/${LATEST}/bundle.yaml | kubectl create -f -
```

### Deploy Prometheus Instance

```bash
# Install Prometheus
kubectl apply -f scripts/monitoring/prometheus.yaml

# Set up monitoring services for cluster and node metrics
kubectl apply -f scripts/monitoring/kube_state_metrics.yaml
kubectl apply -f scripts/monitoring/node_exporter.yaml
```

Wait a couple of minutes for the services to initialize, then verify Prometheus is working:

```bash
curl -G \
  "http://$(minikube ip):30900/api/v1/query" \
  --data-urlencode 'query=up'
```

## 4. Deploy Sample Microservice

We'll deploy [Robot Shop](https://github.com/instana/robot-shop), a sample microservices application for testing.

```bash
# Deploy robot-shop
export DEMO_NAMESPACE=robot-shop
export IS_OPENSHIFT=false
./scripts/setup-demo-microservice.sh

# Switch to the application namespace
kubectl config set-context --current --namespace=$DEMO_NAMESPACE
kubectl get pods

# Set up nginx reverse proxy for health checks
./scripts/setup-nginx.sh
export HOST="http://$(minikube ip):$(kubectl get service rs -o json | jq -r '.spec.ports[0].nodePort')"

# Verify nginx setup
./scripts/test-nginx-routes.sh
```

## 5. Run Krkn-AI

### Discover Cluster Components

Auto-generate an initial Krkn-AI configuration file. Export `PROMETHEUS_URL` first—`discover` uses it to validate the fitness queries it recommends:

```bash
export PROMETHEUS_URL="http://$(minikube ip):30900"

uv run krkn_ai discover -k ./kubeconfig.yaml \
  -n "robot-shop" \
  -pl "service" \
  -nl "kubernetes.io/hostname" \
  -o ./krkn-ai.yaml \
  --skip-pod-name "nginx-proxy.*"
```

This generates `krkn-ai.yaml` containing cluster component details and test configuration. Krkn-AI pre-fills the scenarios your cluster can run, health check URLs from LoadBalancer services, and fitness queries validated against Prometheus. Review the file and adjust as needed—queries that were rejected are left in as comments explaining why.

> **Note:** Without `PROMETHEUS_URL`, `discover` still succeeds but falls back to a single default fitness query instead of the recommended ones.

> **Tip:** Re-running `discover` won't overwrite your file by default. Use `--save-strategy merge` to add new components while keeping edits, or `overwrite` to regenerate. Note: `merge` does not preserve comments inside `cluster_components`.

> **Note:** Some scenarios may not work on Minikube due to limited node access or permissions.

### Start Krkn-AI Tests

```bash
export PROMETHEUS_URL="http://$(minikube ip):30900"

uv run krkn_ai run -vv \
    -r krknhub \
    -c ./krkn-ai.yaml \
    -o ./results \
    -p HOST=$HOST
```

Results will be saved to the `./results` directory, including logs and generation reports.

Operator-managed cancelled runs retain their uploaded checkpoint. The result API
reports the interrupted generation and marks its cohort fitness as cancelled:
raw measurements remain available, while normalized and final totals stay unset.
`resultsFinalized` describes uploader settlement independently from the run's
execution outcome; a cancelled snapshot is finalized but has partial results.

## Scenario Parameter Dependencies

Declare coupled parameter types on a scenario class using `crossover_parameter_groups`, for example `((NamespaceParameter, PodLabelParameter),)`. Each group receives one crossover decision; ungrouped parameters remain independent.

Groups from both parents are combined, merging overlapping groups. A group is exchanged only when both parents have every parameter in it; otherwise none of its parameters cross over. New dependencies require only scenario declarations, not engine changes.

Grouped parameters are read from model fields, including inactive PVC/pod targets and network-mode fields omitted from runner arguments. Crossover snapshots these fields before exchanging complete parameter objects, preserving private pod-owner metadata and mutually exclusive targeting state. Ungrouped parameters cross over only when emitted by both parents.

## Maintaining operator integration compatibility

The runner and artifact-service images declare their operator integration
contract in their final runtime stages:

```dockerfile
LABEL io.krkn.operator-contract.major="1"
```

This custom image-config label is independent of GitHub release versions and
image tags. It is set in `containers/Containerfile.operator` and
`containers/Containerfile.server`, so normal builds inherit it without workflow
inputs or per-release edits. The full standalone Krkn-AI image does not declare
this operator-specific contract.

### Contract 1

Contract 1 includes durable operator/child cancellation, explicit cancelled
completion markers and manifests, and retained partial-generation results.
The integration remains at major 1 while it is unreleased. Build and deploy the
matching operator, runner, uploader, and console changes together; the runner and
uploader agree on the explicit `outcome: "cancelled"` completion marker.

Configuration validation and explicit artifact deletion remain available through
`POST /v1/configs/validate` and `DELETE /v1/runs/{uid}`. Cancellation does not call
the deletion endpoint. Completed generations keep finalized scores; an
interrupted generation retains raw measurements but exposes cancelled, null
normalized/final scores. Artifact readers preserve the last committed immutable
checkpoint while the next checkpoint uploads.

The operator's Helm and OLM release workflows select the newest stable release
whose runner and service images both advertise the supported contract major.
Unlabelled images, including releases predating this contract, are ineligible.
The workflows inspect image metadata and package the inspected immutable image
references. They do not start containers, create tokens, or call service or
cluster APIs. Maintaining the label correctly is the compatibility guarantee.

### When to change the label

- Bug fixes, internal refactoring, algorithm improvements, and backward-compatible
  optional API additions keep the current value. Do not increment it for every
  application release or synchronize application version numbers across repos.
- Removing or renaming required routes, changing required request/response
  formats or status codes, or breaking runner/environment/artifact semantics
  requires the next contract major in **both** runtime Containerfiles.
- Coordinate that breaking change with the operator's supported contract major
  before promotion. Older operators keep selecting the newest release supporting
  their contract; never relabel or overwrite an older release to claim support.

Publish both operator images under the same release tag before promoting the
GitHub release to stable. No per-release compatibility matrix is maintained.
Verify built metadata locally, for example:

```bash
podman image inspect quay.io/krkn-chaos/krkn-ai-operator:<tag> \
  --format '{{ index .Config.Labels "io.krkn.operator-contract.major" }}'
podman image inspect quay.io/krkn-chaos/krkn-ai-service:<tag> \
  --format '{{ index .Config.Labels "io.krkn.operator-contract.major" }}'
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `kubectl` commands fail | Ensure Minikube is running: `minikube status` |
| Prometheus query returns empty | Wait 2-3 minutes for metrics to populate |
| Pods stuck in `Pending` state | Check resources: `minikube ssh -- df -h` |
| Cannot reach services | Verify Minikube IP: `minikube ip` |
