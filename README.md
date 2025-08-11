# Chaos AI 🧬⚡

<br/>

> [!CAUTION]  
> __The tool is currently in under active development, use it at your own risk.__

<br/>

An intelligent chaos engineering framework that uses genetic algorithms to optimize chaos scenarios for Kubernetes/OpenShift applications. Chaos AI automatically evolves and discovers the most effective chaos experiments to test your system's resilience.

## 🌟 Features

- **Genetic Algorithm Optimization**: Automatically evolves chaos scenarios to find optimal testing strategies
- **Multi-Scenario Support**: Pod failures, container scenarios, node resource exhaustion, and application outages
- **Kubernetes/OpenShift Integration**: Native support for both platforms
- **Health Monitoring**: Continuous monitoring of application health during chaos experiments
- **Prometheus Integration**: Metrics-driven fitness evaluation
- **Configurable Fitness Functions**: Point-based and range-based fitness evaluation
- **Population Evolution**: Maintains and evolves populations of chaos scenarios across generations

## 🔧 Architecture

Chaos AI consists of several key components:

- **Genetic Algorithm Engine**: Core optimization logic that evolves chaos scenarios
- **Krkn Runner**: Integration with [Krkn](https://github.com/krkn-chaos/krkn) chaos engineering framework
- **Health Check Watcher**: Monitors application endpoints during experiments
- **Scenario Factory**: Creates and manages different types of chaos scenarios
- **Configuration Manager**: Handles complex configuration parsing and validation

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- `uv` package manager (recommended) or `pip`
- [podman](https://podman.io/)
- Kubernetes or OpenShift cluster access file (kubeconfig)

### Setup Virtual Environment

```bash
# Install uv if you haven't already
pip install uv

# Create and activate virtual environment
uv venv --python 3.9
source .venv/bin/activate

# Install Chaos AI in development mode
uv pip install -e .
```

### Deploy Sample Microservice

For demonstration purposes, deploy the robot-shop microservice:

```bash
export DEMO_NAMESPACE=robot-shop
export IS_OPENSHIFT=true
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

## 📝 Configuration

Chaos AI uses YAML configuration files to define experiments. Here's a sample configuration:

```yaml
# Path to your kubeconfig file
kubeconfig_file_path: "./tmp/kubeconfig.yaml"

# Genetic algorithm parameters
generations: 5
population_size: 10
composition_rate: 0.3
population_injection_rate: 0.1

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
  - name: shipping
    url: "$HOST/shipping/codes"

# Chaos scenarios to evolve
scenario:
  pod-scenarios:
    namespace:
      - robot-shop
    pod_label:
      - service=mongodb
      - service=cart
  
  application-outages:
    namespace:
      - robot-shop
    pod_selector:
      - app=web
  
  node-cpu-hog:
    node_selector:
      - worker-node
```

### Configuration Options

| Section | Description |
|---------|-------------|
| `kubeconfig_file_path` | Path to Kubernetes configuration file |
| `generations` | Number of evolutionary generations to run |
| `population_size` | Size of each generation's population |
| `composition_rate` | Rate of crossover between scenarios |
| `population_injection_rate` | Rate of introducing new random scenarios |
| `fitness_function` | Metrics query and evaluation method |
| `health_checks` | Application endpoints to monitor |
| `scenario` | Chaos scenario configurations |

## 🎯 Usage

### Basic Usage

```bash
# Run chaos AI with default configuration
uv run chaos_ai run -c config/robot-shop-default.yaml -o ./tmp/results/ -p HOST=$HOST

# With custom Prometheus settings
export PROMETHEUS_URL='https://your-prometheus-url'
export PROMETHEUS_TOKEN='your-prometheus-token'
uv run chaos_ai run -c config/robot-shop-default.yaml -o ./tmp/results/ -p HOST=$HOST
```

### CLI Options

```bash
$ uv run chaos_ai run --help
Usage: chaos_ai run [OPTIONS]

Options:
  -c, --config TEXT               Path to chaos AI config file.
  -o, --output TEXT               Directory to save results.
  -f, --format [json|yaml]        Format of the output file.
  -r, --runner-type [krknctl|krknhub]
                                  Type of chaos engine to use.
  -p, --param TEXT                Additional parameters for config file in
                                  key=value format.
  -v, --verbose                   Increase verbosity of output.
  --help                          Show this message and exit.
```

### Understanding Results

Chaos AI saves results in the specified output directory:

```
.
└── results/
    ├── reports/
    │   ├── health_check_report.csv
    │   └── graphs/
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

1. **Initial Population**: Creates random chaos scenarios based on your configuration
2. **Fitness Evaluation**: Runs each scenario and measures system response using Prometheus metrics
3. **Selection**: Identifies the most effective scenarios based on fitness scores
4. **Evolution**: Creates new scenarios through crossover and mutation
5. **Health Monitoring**: Continuously monitors application health during experiments
6. **Iteration**: Repeats the process across multiple generations to find optimal scenarios

## 🔧 Development

### Project Structure

```
chaos_ai/
├── algorithm/          # Genetic algorithm implementation
├── chaos_engines/      # Krkn integration and health monitoring
├── cli/               # Command-line interface
├── models/            # Data models and configuration
└── utils/             # Utilities and logging
```

### Running Tests

```bash
# Test application routes
./tests/test-nginx-routes.sh

# Run unit tests (if available)
python -m pytest tests/
```


## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 🐛 Troubleshooting

### Common Issues

**Config file not found**: Ensure the path to your configuration file is correct and the file exists.

**Kubeconfig issues**: Verify your kubeconfig path is correct and you have cluster access:
```bash
kubectl cluster-info
```

**Prometheus connection**: If using external Prometheus, ensure URL and token are correctly set:
```bash
export PROMETHEUS_URL='https://your-prometheus-url'
export PROMETHEUS_TOKEN='your-token'
```

**Permission errors**: Ensure your Kubernetes user has sufficient permissions for the target namespaces.
