# Krkn-AI 🧬⚡

[![Quay](https://img.shields.io/badge/quay.io-krkn--ai-blue?logo=quay)](https://quay.io/repository/krkn-chaos/krkn-ai)

> [!CAUTION]
> **The tool is currently under active development, use it at your own risk.**

An intelligent chaos engineering framework that uses genetic algorithms to evolve and discover the most effective chaos experiments for testing your Kubernetes/OpenShift application's resilience.

## ⚙️ How It Works

1. **Initial Population** — Creates random chaos scenarios from your configuration
2. **Fitness Evaluation** — Runs each scenario and measures system response via Prometheus metrics
3. **Selection** — Identifies the most impactful scenarios based on fitness scores
4. **Evolution** — Generates new scenarios through crossover and mutation
5. **Iteration** — Repeats across multiple generations to converge on optimal scenarios

## 📋 Prerequisites

- [krknctl](https://github.com/krkn-chaos/krknctl)
- [oc](https://mirror.openshift.com/pub/openshift-v4/clients/ocp/) / kubectl
- Python 3.11+
- `uv` package manager
- [podman](https://podman.io/)
- [helm 3.x](https://helm.sh/docs/v3/intro/install/)
- Kubernetes/OpenShift cluster kubeconfig

The `operator` runner does not require local `krknctl`, Podman, or `oc`; it
uses the Kubernetes API and an installed `krkn-operator`. Those tools remain
required for the default local/container HUB and discovery workflows.

## 🚀 Getting Started

### Install from source

```bash
pip install uv
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -e .
krkn_ai --help
```

### Install from GitHub

```bash
pip install uv
uv venv --python 3.11 && source .venv/bin/activate
uv pip install "krkn-ai @ git+https://github.com/krkn-chaos/krkn-ai.git"
krkn_ai --help
```

### Deploy Sample Microservice

```bash
export DEMO_NAMESPACE=robot-shop
./scripts/setup-demo-microservice.sh
kubectl config set-context --current --namespace=$DEMO_NAMESPACE
```

```bash
# Setup NGINX reverse proxy
./scripts/setup-nginx.sh
```

```bash
# Test Endpoints

# For clusters that provide a LoadBalancer hostname
export HOST="http://$(kubectl get service rs -o json | jq -r '.status.loadBalancer.ingress[0].hostname')"
./scripts/test-nginx-routes.sh

#For local environments, where a LoadBalancer hostname may not be available
kubectl port-forward svc/rs 8080:80 -n robot-shop
# In a separate terminal
export HOST=http://localhost:8080
./scripts/test-nginx-routes.sh
```

### Generate Configuration

Use the `discover` command to auto-generate a config from your running cluster:

```bash
krkn_ai discover \
  -k ./tmp/kubeconfig.yaml \
  -n "robot-shop" \
  -pl "service" \
  -nl "kubernetes.io/hostname" \
  -o ./tmp/krkn-ai.yaml \
  --skip-pod-name "nginx-proxy.*"
```

By default `discover` won't overwrite an existing output file. Control this with `--save-strategy`:

| Strategy         | Behavior                                              |
|------------------|-------------------------------------------------------|
| `skip` (default) | Keep the existing file, do nothing.                   |
| `overwrite`      | Replace the file with a fresh config.                 |
| `merge`          | Keep your edits, add newly discovered components.     |

```bash
krkn_ai discover -k ./tmp/kubeconfig.yaml -o ./tmp/krkn-ai.yaml --save-strategy merge
```

`merge` preserves manual edits (e.g. `disabled: true`) and adds newly discovered components. Note: comments inside `cluster_components` are not preserved after a merge.

Besides `cluster_components`, `discover` also works out which scenarios your cluster can run, builds health check URLs from LoadBalancer services, and recommends fitness queries validated against your Prometheus. Scenarios and health checks are only regenerated on a fresh write or `overwrite`.

On OpenShift, the Prometheus URL and token are discovered from the cluster's Thanos route, so no setup is needed. On other clusters, set `PROMETHEUS_URL` (and `PROMETHEUS_TOKEN` if your Prometheus requires auth), otherwise a single default fitness query is written instead of the recommendations.

Key config options:

```yaml
kubeconfig_file_path: "./tmp/kubeconfig.yaml"
wait_duration: 30          # seconds between scenarios

# Algorithm selector — currently "genetic", future engines will add their own section
algorithm: genetic

# Genetic algorithm parameters (separate section per algorithm)
genetic:
  generations: 5
  population_size: 10
  composition_rate: 0.3
  population_injection_rate: 0.1

fitness_function:
  items:
    # Coefficients are normalized proportionally (8:2 becomes 0.8:0.2).
    - query: 'sum(kube_pod_container_status_restarts_total{namespace="robot-shop"})'
      type: point
      weight: 8
    - query: 'avg(node_memory_Active_bytes)'
      type: range
      weight: 2
  include_krkn_failure: true

health_checks:
  stop_watcher_on_failure: false
  applications:
    - name: cart
      url: "$HOST/cart/add/1/Watson/1"

scenario:
  pod-scenarios:
    enable: true
  application-outages:
    enable: true
  node-cpu-hog:
    enable: true
```

> **Note:** Config files using the old flat layout (GA fields at root level) are still supported — they are automatically migrated on load.

See the full config reference in the [docs](https://krkn-chaos.dev/docs/krkn_ai/config/).

### Run Experiments

```bash
krkn_ai run \
  -c ./tmp/krkn-ai.yaml \
  -o ./tmp/results/ \
  -p HOST=$HOST
```

### Run with the Kubernetes operator

The `operator` runner creates a `KrknScenarioRun` custom resource for each
scenario instead of invoking Podman or `krknctl` locally. The
`krkn-operator` controller creates the scenario pod and reports its result
back to krkn-ai.

Manual execution requires the `krkn-operator` CRD and an in-cluster identity
with permission to create and read `KrknScenarioRun` resources:

```bash
export KUBECONFIG=/path/to/kubeconfig
export KRKNAI_NAMESPACE=krkn-operator
export KRKNAI_RUN_NAME=manual-run
export KRKNAI_RUN_UID=<KrknAIRun-uid>
export KRKNAI_TARGET_REQUEST_ID=self
export KRKNAI_PROVIDER=krkn-operator
export KRKNAI_CLUSTER=self
export KRKNAI_SCENARIO_MAX_RETRIES=0

krkn_ai run \
  -c ./tmp/krkn-ai.yaml \
  -k "$KUBECONFIG" \
  -o ./tmp/operator-results \
  --runner-type operator
```

The `KRKNAI_RUN_UID` value is used as the owner reference for child
`KrknScenarioRun` resources. When running outside a `KrknAIRun` controller,
use a real parent UID or omit owner-reference cleanup expectations.

For the Kubernetes deployment workflow, including the per-run configuration
ConfigMap, `KrknAIRun` manifest, target Secret format, RBAC, dedicated image,
and cleanup commands, see
[`hack/README.md`](hack/README.md) and
[`containers/README.md`](containers/README.md).

## 💻 CLI Reference

| Command | Key Options |
|---------|-------------|
| `discover` | `-k` kubeconfig, `-n` namespace, `-pl` pod-label, `-nl` node-label, `-o` output, `-v` verbose, `--skip-pod-name`, `-S` save-strategy, `--learned-weights` |
| `run` | `-k` kubeconfig, `-c` config, `-o` output dir, `-f` format, `-r` runner type, `-p` params, `--monitoring`, `--port` |
| `monitor` | `-o` results dir, `-p` port |

Run any command with `--help` for full details.

## 🔍 Advanced Filtering

The `-n`, `-pl`, `-nl`, and `--skip-pod-name` options support flexible pattern matching:

| Pattern | Description |
|---------|-------------|
| `robot-shop` | Exact match |
| `robot-shop,default` | Match either |
| `openshift-.*` | Regex match |
| `*` | Match all |
| `!kube-system` | Exclude |
| `*,!kube-.*` | All except kube-* |
| `openshift-.*,!openshift-operators` | Regex with exclusion |

## 📊 Monitoring Dashboard

Launch live monitoring alongside an experiment:

```bash
krkn_ai run -c ./tmp/krkn-ai.yaml -o ./tmp/results/ --monitoring
# use --port 9000 to change from the default 8501
```

View results from a completed run:

```bash
krkn_ai monitor -o ./tmp/results/
```

## 📁 Output Structure

```
results/
└── <run_uuid>/
    ├── run.log
    ├── krkn-ai.yaml
    ├── results.json
    ├── learned_weights.json   # only when using fitness_function.items
    ├── reports/
    │   ├── health_check_report.csv
    │   ├── all.csv
    │   ├── best_scenarios.yaml
    │   └── graphs/
    ├── yaml/
    │   ├── generation_0/
    │   └── generation_1/
    └── logs/
```

`learned_weights.json` scores each fitness query by how much its value varied across scenarios. Pass it to the next `discover` with `--learned-weights` to prioritize the queries that actually distinguish scenarios. It is written only when the config uses `fitness_function.items` and at least one query varied across the run.

> You can also run Krkn-AI as a container with Podman or on Kubernetes. See [container instructions](./containers/README.md).

## 🤝 Contributing

1. Fork the repository and create a feature branch
2. Install dev tooling and pre-commit hooks:

```bash
source .venv/bin/activate
uv pip install -e .[dev]
pre-commit install
```
3. Run static checks before committing:

```bash
pre-commit run --all-files
# or individually: ruff check/format, mypy, hadolint
```

4. Run the test suite and make sure all tests pass:

```bash
pytest
```

See [tests/README.md](./tests/README.md) for details on running specific modules, writing new tests, and fixture usage.

5. Open a pull request against `main`
