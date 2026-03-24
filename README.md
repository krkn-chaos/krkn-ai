# Krkn-AI 🧬⚡

[![Quay](https://img.shields.io/badge/quay.io-krkn--ai-blue?logo=quay)](https://quay.io/repository/krkn-chaos/krkn-ai)


> [!CAUTION]  
> __The tool is currently in under active development, use it at your own risk.__

An intelligent chaos engineering framework that uses genetic algorithms to optimize chaos scenarios for Kubernetes/OpenShift applications. Krkn-AI automatically evolves and discovers the most effective chaos experiments to test your system's resilience.

## 🌟 Features

- **Genetic Algorithm Optimization**: Automatically evolves chaos scenarios to find optimal testing strategies
- **Multi-Scenario Support**: Pod failures, container scenarios, node resource exhaustion, and application outages
- **Kubernetes/OpenShift Integration**: Native support for both platforms
- **Health Monitoring**: Continuous monitoring of application health during chaos experiments
- **Prometheus Integration**: Metrics-driven fitness evaluation
- **Configurable Fitness Functions**: Point-based and range-based fitness evaluation
- **Population Evolution**: Maintains and evolves populations of chaos scenarios across generations

## 🚀 Getting Started

### Prerequisites

- [krknctl](https://github.com/krkn-chaos/krknctl)
- Python 3.11+
- `uv` package manager (recommended) or `pip`
- [podman](https://podman.io/)
- [helm](https://helm.sh/docs/intro/install/)
- Kubernetes cluster access file (kubeconfig)

### Setup Virtual Environment

```bash
# Install uv if you haven't already
pip install uv

# Create and activate virtual environment
uv venv --python 3.11
source .venv/bin/activate

# Install Krkn-AI in development mode
uv pip install -e .

# Check Installation
uv run krkn_ai --help
```

### Deploy Sample Microservice

For demonstration purposes, deploy the robot-shop microservice:

```bash
export DEMO_NAMESPACE=robot-shop
export IS_OPENSHIFT=true
#set IS_OPENSHIFT=false for kubernetes cluster
./scripts/setup-demo-microservice.sh

# Set context to the demo namespace
oc config set-context --current --namespace=$DEMO_NAMESPACE
# or for kubectl:
# kubectl config set-context --current --namespace=$DEMO_NAMESPACE
```

### Setup Monitoring and Testing

```bash
# Setup NGINX reverse proxy for external access
./scripts/setup-nginx.sh

# Test application endpoints
./scripts/test-nginx-routes.sh

export HOST="http://$(kubectl get service rs -o json | jq -r '.status.loadBalancer.ingress[0].hostname')"
```

## 📝 Generate Configuration

Krkn-AI uses YAML configuration files to define experiments. You can generate a sample config file dynamically by running Krkn-AI discover command.

```bash
uv run krkn_ai discover -k ./tmp/kubeconfig.yaml \
  -n "robot-shop" \
  -pl "service" \
  -nl "kubernetes.io/hostname" \
  -o ./tmp/krkn-ai.yaml \
  --skip-pod-name "nginx-proxy.*"
```

### Pattern Syntax for Filtering

The `-n` (namespace), `-pl` (pod-label), `-nl` (node-label), and `--skip-pod-name` options support flexible pattern matching:

| Pattern | Description |
|---------|-------------|
| `robot-shop` | Match exactly "robot-shop" |
| `robot-shop,default` | Match "robot-shop" OR "default" |
| `openshift-.*` | Regex: match namespaces starting with "openshift-" |
| `*` | Match all |
| `!kube-system` | Match all EXCEPT "kube-system" |
| `*,!kube-.*` | Match all except kube-* namespaces |
| `openshift-.*,!openshift-operators` | Match openshift-* but exclude operators |

**Examples:**

```bash
# Discover in all namespaces except kube-system and openshift-*
uv run krkn_ai discover -k ./tmp/kubeconfig.yaml \
  -n "!kube-system,!openshift-.*" \
  -o ./tmp/krkn-ai.yaml

# Discover in openshift namespaces but exclude operators
uv run krkn_ai discover -k ./tmp/kubeconfig.yaml \
  -n "openshift-.*,!openshift-operators" \
  -o ./tmp/krkn-ai.yaml
```

```yaml
# Path to your kubeconfig file
kubeconfig_file_path: "./tmp/kubeconfig.yaml"

# Optional: Random seed for reproducible runs
# seed: 42

# Genetic algorithm parameters
generations: 5
population_size: 10
composition_rate: 0.3
population_injection_rate: 0.1

# Uncomment the line below to enable runs by duration instead of generation count
# duration: 600

# Duration to wait before running next scenario (seconds)
wait_duration: 30

# Elasticsearch configuration for storing run results (Optional)
elastic:
  enable: false  # Set to true to enable Elasticsearch integration
  verify_certs: true  # Verify SSL certificates
  server: "http://localhost"  # Elasticsearch URL
  port: 9200  # Elasticsearch port
  username: "$ES_USER"  # Elasticsearch username
  password: "$__ES_PASSWORD"  # Elasticsearch password (start param with __ to treat as private)
  index: "krkn-ai"  # Index prefix for storing Krkn-AI config and results

# Specify how result filenames are formatted
output:
  result_name_fmt: "scenario_%s.yaml"
  graph_name_fmt: "scenario_%s.png"
  log_name_fmt: "scenario_%s.log"

# Fitness function configuration
fitness_function:
  query: 'sum(kube_pod_container_status_restarts_total{namespace="robot-shop"})'
  type: point  # or 'range'
  include_krkn_failure: true

# Health endpoints to monitor
health_checks:
  stop_watcher_on_failure: false
  applications:
  - name: cart
    url: "$HOST/cart/add/1/Watson/1"
  - name: catalogue
    url: "$HOST/catalogue/categories"

# Chaos scenarios to evolve
scenario:
  pod-scenarios:
    enable: true
  application-outages:
    enable: false
  container-scenarios:
    enable: false
  node-cpu-hog:
    enable: false
  node-memory-hog:
    enable: false
  kubevirt-outage:
    enable: false

# Cluster components to consider for Krkn-AI testing
cluster_components:
  namespaces:
  - name: robot-shop
    pods:
    - containers:
      - name: cart
      labels:
        service: cart
      name: cart-7cd6c77dbf-j4gsv
    - containers:
      - name: catalogue
      labels:
        service: catalogue
      name: catalogue-94df6b9b-pjgsr
  nodes:
  - labels:
      kubernetes.io/hostname: node-1
    name: node-1
  - labels:
      kubernetes.io/hostname: node-2
    name: node-2
```

You can modify `krkn-ai.yaml` as per your requirement to include/exclude any cluster components, scenarios, fitness function SLOs or health check endpoints for the Krkn-AI testing.


## 🎯 Usage

### Basic Usage

```bash
# Configure custom Prometheus Querier endpoint and token
export PROMETHEUS_URL='https://your-prometheus-url'
export PROMETHEUS_TOKEN='your-prometheus-token'

# Configure elastic search properties (optional)
export ES_USER="elasticsearch-username"
export __ES_PASSWORD="elasticsearch-password"

# Run Krkn-AI
uv run krkn_ai run \
  -c ./tmp/krkn-ai.yaml \
  -o ./tmp/results/ \
  -p HOST=$HOST \
  -p ES_USER=$ES_USER -p __ES_PASSWORD=$__ES_PASSWORD
```

### CLI Options

```bash
$ uv run krkn_ai discover --help
Usage: krkn_ai discover [OPTIONS]

  Discover components for Krkn-AI tests

Options:
  -k, --kubeconfig TEXT   Path to cluster kubeconfig file.
  -o, --output TEXT       Path to save config file.
  -n, --namespace TEXT    Namespace(s) to discover components in. Supports
                          Regex and comma separated values.
  -pl, --pod-label TEXT   Pod Label Keys(s) to filter. Supports Regex and
                          comma separated values.
  -nl, --node-label TEXT  Node Label Keys(s) to filter. Supports Regex and
                          comma separated values.
  -v, --verbose           Increase verbosity of output.
  --skip-pod-name TEXT    Pod name to skip. Supports comma separated values
                          with regex.
  --help                  Show this message and exit.



$ uv run krkn_ai run --help
Usage: krkn_ai run [OPTIONS]

  Run Krkn-AI tests

Options:
  -c, --config TEXT               Path to Krkn-AI config file.
  -o, --output TEXT               Directory to save results.
  -f, --format [json|yaml]        Format of the output file.
  -r, --runner-type [krknctl|krknhub]
                                  Type of krkn engine to use.
  -p, --param TEXT                Additional parameters for config file in
                                  key=value format.
  -v, --verbose                   Increase verbosity of output.
  --help                          Show this message and exit.
```

> **Note:** You can also run Krkn-AI as a container with Podman or on Kubernetes. See [container instructions](./containers/README.md).

### Understanding Results

Krkn-AI saves results in the specified output directory:

```
.
└── results/
    ├── reports/
    │   ├── health_check_report.csv
    │   └── graphs/
    │       ├── best_generation.png
    │       ├── scenario_1.png
    │       ├── scenario_2.png
    │       └── ...
    ├── yaml/
    │   ├── generation_0/
    │   │   ├── scenario_1.yaml
    │   │   ├── scenario_2.yaml
    │   │   └── ...
    │   └── generation_1/
    │       └── ...
    ├── log/
    │   ├── scenario_1.log
    │   ├── scenario_2.log
    │   └── ...
    ├── best_scenarios.json
    └── config.yaml
```

## 🧬 How It Works

The current version of Krkn-AI leverages an [evolutionary algorithm](https://en.wikipedia.org/wiki/Evolutionary_algorithm), an optimization technique that uses heuristics to identify chaos scenarios and components that impact the stability of your cluster and applications.

1. **Initial Population**: Creates random chaos scenarios based on your configuration
2. **Fitness Evaluation**: Runs each scenario and measures system response using Prometheus metrics
3. **Selection**: Identifies the most effective scenarios based on fitness scores
4. **Evolution**: Creates new scenarios through crossover and mutation
5. **Health Monitoring**: Continuously monitors application health during experiments
6. **Iteration**: Repeats the process across multiple generations to find optimal scenarios


## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes and run the [static checks](#static-checks) (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Static Checks

Developers should run the project's static checks locally before committing. Below are recommended commands and notes for common environments (PowerShell / Bash).


- Install tooling used for checks:

```bash
# Activate Virtual Environment
source .venv/bin/activate

# Install dev requirement
uv pip install -r requirements-dev.txt
```

- Install Git hooks (runs once per developer):

```bash
pre-commit install
pre-commit autoupdate
```

- Run all pre-commit hooks against the repository (fast, recommended):

```bash
pre-commit run --all-files
```

- Run individual tools directly:

```bash
# Ruff (linter/formatter)
ruff check .
ruff format .

# Mypy (type checking)
mypy --config-file mypy.ini krkn_ai

# Hadolint (Dockerfile/Containerfile linting) - Docker must be available
hadolint containers/Containerfile
```

Notes:
- The `pre-commit` configuration runs `ruff`, various file checks, and `hadolint` for container files. If `hadolint` fails with a Docker error, ensure Docker Desktop/daemon is running on your machine (the hook needs to query Docker to validate containerfile context).
- Use `pre-commit run --all-files` to validate changes before pushing. CI will also run these checks.
