# Krkn-AI Dashboard

## Overview

The Krkn-AI Dashboard is an interactive web-based visualization tool that transforms raw chaos experiment results into intuitive, explorable visual representations. It enables engineers to quickly understand system behavior, detect anomalies, and focus on the most impactful failure signals.

## Features

### 📊 Interactive Visualizations
- **Fitness Score Trends**: Line charts showing best, average, and worst fitness scores across generations
- **Health Check Monitoring**: Stacked bar charts displaying success/failure rates by application
- **Top Scenarios Table**: Sortable table of best-performing scenarios

### 🔍 Automatic Anomaly Detection
- **Fitness Drops**: Detects sudden drops in fitness scores (>10%)
- **Health Check Failures**: Identifies applications with high failure rates (>20%)
- **Response Time Spikes**: Flags unusual response time increases
- **Success Rate Alerts**: Highlights low experiment success rates (<90%)

### 🎨 Modern UI/UX
- Dark-themed, responsive design
- Interactive Chart.js visualizations
- Hover effects and smooth animations
- Mobile-friendly layout

## Usage

### Generate Dashboard from Results

```bash
# Using CLI command
krkn_ai dashboard -r <results_directory> -o <output_file>

# Example
krkn_ai dashboard -r ./results -o dashboard.html
```

### Python API

```python
from krkn_ai.dashboard.generator import DashboardGenerator

# Generate dashboard
generator = DashboardGenerator("./results")
dashboard_path = generator.generate("dashboard.html")

# Open in browser
import webbrowser
webbrowser.open(f"file://{dashboard_path}")
```

## Input Data Format

The dashboard expects Krkn-AI results in the following structure:

```
results/
├── krkn-ai.yaml                    # Experiment configuration
├── best_scenarios.json             # Best scenarios per generation
├── reports/
│   └── health_check_report.csv     # Health check results
├── yaml/
│   └── generation_*/
│       └── scenario_*.yaml         # Scenario results (YAML)
└── json/
    └── generation_*/
        └── scenario_*.json         # Scenario results (JSON)
```

### Required Files

1. **`krkn-ai.yaml`**: Experiment configuration
2. **`best_scenarios.json`**: Summary of best scenarios
3. **`health_check_report.csv`**: Health check data (optional)
4. **Scenario files**: Individual scenario results in YAML or JSON format

## Dashboard Sections

### 1. Summary Statistics
- Best Fitness Score
- Total Scenarios Tested
- Success Rate
- Number of Generations

### 2. Anomalies Detected
- Severity-ranked anomalies
- Detailed descriptions
- Actionable insights

### 3. Fitness Score Trends
- Multi-line chart showing evolution across generations
- Best, average, and worst fitness scores
- Interactive tooltips

### 4. Health Check Status
- Stacked bar chart by application
- Success vs. failure counts
- Identifies problematic services

### 5. Top Scenarios
- Ranked table of best-performing scenarios
- Sortable by fitness score
- Includes generation and status information

## Anomaly Detection

The dashboard automatically detects the following anomalies:

| Anomaly Type | Detection Criteria | Severity |
|--------------|-------------------|----------|
| Fitness Drop | >10% decrease between generations | 1-10 (based on drop %) |
| Health Check Failure | >20% failure rate for an application | 1-10 (based on failure %) |
| Response Time Spike | >2 standard deviations above mean | 1-10 (based on spike magnitude) |
| Low Success Rate | <90% overall success rate | 1-10 (based on success %) |

## Customization

### Anomaly Sensitivity

Adjust anomaly detection sensitivity:

```python
from krkn_ai.dashboard.anomaly_detector import AnomalyDetector

detector = AnomalyDetector(data, sensitivity=1.5)  # More sensitive
anomalies = detector.detect_all()
```

### Custom Styling

Modify the dashboard template:
- Edit `krkn_ai/dashboard/templates/dashboard.html`
- Customize CSS variables in `:root` section
- Adjust chart colors and styling

## Technical Details

### Architecture
- **Pure Client-Side**: No server required
- **Self-Contained**: Single HTML file with embedded data
- **Portable**: Works offline, easy to share

### Technology Stack
- **Chart.js 4.4.1**: Interactive charts
- **Vanilla JavaScript**: No framework dependencies
- **CSS3**: Modern styling with gradients and animations

### Browser Compatibility
- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)

## Examples

### Sample Data Generation

Generate sample data for testing:

```bash
python krkn_ai/dashboard/sample_data_generator.py
```

This creates a `sample_results/` directory with:
- 10 generations
- 5 scenarios per generation
- Health check data for 3 applications
- Intentional anomalies for testing

### Opening the Dashboard

After generation, open the dashboard:

```bash
# Linux/Mac
xdg-open dashboard.html

# Or specify browser
firefox dashboard.html
google-chrome dashboard.html
```

## Troubleshooting

### Dashboard Not Loading
- Ensure all required files exist in results directory
- Check browser console for JavaScript errors
- Verify JSON/YAML files are valid

### Charts Not Rendering
- Ensure Chart.js CDN is accessible
- Check browser compatibility
- Verify data format is correct

### Missing Data
- Confirm scenario files contain `fitness_result` field
- Verify health check CSV has required columns
- Check file paths in results directory

## Contributing

To add new visualizations or features:

1. **Data Aggregation**: Modify `krkn_ai/dashboard/aggregator.py`
2. **Anomaly Detection**: Update `krkn_ai/dashboard/anomaly_detector.py`
3. **Visualization**: Edit `krkn_ai/dashboard/templates/dashboard.html`
4. **Generator Logic**: Adjust `krkn_ai/dashboard/generator.py`

## License

Same as Krkn-AI project (Apache 2.0)
