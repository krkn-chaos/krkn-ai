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

Auto-generate an initial Krkn-AI configuration file:

```bash
uv run krkn_ai discover -k ./kubeconfig.yaml \
  -n "robot-shop" \
  -pl "service" \
  -nl "kubernetes.io/hostname" \
  -o ./krkn-ai.yaml \
  --skip-pod-name "nginx-proxy.*"
```

This generates `krkn-ai.yaml` containing cluster component details and boilerplate test configuration. Review and modify the file as needed—add health check endpoints, adjust the fitness function, and enable desired scenarios.

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

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `kubectl` commands fail | Ensure Minikube is running: `minikube status` |
| Prometheus query returns empty | Wait 2-3 minutes for metrics to populate |
| Pods stuck in `Pending` state | Check resources: `minikube ssh -- df -h` |
| Cannot reach services | Verify Minikube IP: `minikube ip` |
