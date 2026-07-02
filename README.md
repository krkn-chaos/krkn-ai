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

Key config options:

```yaml
kubeconfig_file_path: "./tmp/kubeconfig.yaml"

generations: 5
population_size: 10
composition_rate: 0.3
population_injection_rate: 0.1
wait_duration: 30          # seconds between scenarios

fitness_function:
  query: 'sum(kube_pod_container_status_restarts_total{namespace="robot-shop"})'
  type: point               # or 'range'
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

See the full config reference in the [docs](https://krkn-chaos.dev/docs/krkn_ai/config/).

### Run Experiments

```bash
krkn_ai run \
  -c ./tmp/krkn-ai.yaml \
  -o ./tmp/results/ \
  -p HOST=$HOST
```

## 💻 CLI Reference

| Command | Key Options |
|---------|-------------|
| `discover` | `-k` kubeconfig, `-n` namespace, `-pl` pod-label, `-nl` node-label, `-o` output, `--skip-pod-name`, `--save-strategy` |
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

4. Open a pull request against `main`
