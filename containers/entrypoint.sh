#!/bin/bash
set -e

# Activate the uv virtual environment
source /app/.venv/bin/activate

# Function to display usage
usage() {
    echo "Usage: Set MODE environment variable to 'discover' or 'run'"
    echo ""
    echo "For DISCOVER mode:"
    echo "  Required: KUBECONFIG"
    echo "  Optional: OUTPUT_DIR, NAMESPACE, POD_LABEL, NODE_LABEL, SKIP_POD_NAME, VERBOSE"
    echo ""
    echo "For RUN mode:"
    echo "  Required: CONFIG_FILE"
    echo "  Optional: OUTPUT_DIR, FORMAT, RUNNER_TYPE, EXTRA_PARAMS, VERBOSE"
    echo ""
    echo "Example (discover):"
    echo "  podman run -v ./input:/input -v ./output:/output \\"
    echo "    -e MODE=discover \\"
    echo "    -e KUBECONFIG=/input/kubeconfig \\"
    echo "    -e NAMESPACE=default \\"
    echo "    krkn-ai"
    echo ""
    echo "Example (run):"
    echo "  podman run -v ./input:/input -v ./output:/output \\"
    echo "    -e MODE=run \\"
    echo "    -e CONFIG_FILE=/input/krkn-ai.yaml \\"
    echo "    -e RUNNER_TYPE=krknctl \\"
    echo "    krkn-ai"
    exit 1
}

# Validate MODE is set
if [ -z "$MODE" ]; then
    echo "ERROR: MODE environment variable is not set"
    usage
fi

# Convert MODE to lowercase for comparison
MODE_LOWER=$(echo "$MODE" | tr '[:upper:]' '[:lower:]')

case "$MODE_LOWER" in
    discover)
        echo "Running in DISCOVER mode..."

        # Validate required parameters
        if [ ! -f "$KUBECONFIG" ]; then
            echo "ERROR: KUBECONFIG file not found at: $KUBECONFIG"
            exit 1
        fi

        # Build the command
        CMD=(krkn_ai discover --kubeconfig "$KUBECONFIG" --output "$OUTPUT_DIR/krkn-ai.yaml")

        # Add optional parameters
        if [ -n "$NAMESPACE" ]; then
            CMD+=(--namespace "$NAMESPACE")
        fi
        if [ -n "$POD_LABEL" ]; then
            CMD+=(--pod-label "$POD_LABEL")
        fi
        if [ -n "$POD_LABEL" ]; then
            CMD+=(--node-label "$NODE_LABEL")
        fi
        if [ -n "$SKIP_POD_NAME" ]; then
            CMD+=(--skip-pod-name "$SKIP_POD_NAME")
        fi
        # Add verbosity flags
        if [ "$VERBOSE" -ge 1 ]; then
            for ((i=0; i<$VERBOSE; i++)); do
                CMD+=(-v)
            done
        fi

        echo "Executing: ${CMD[*]}"
        "${CMD[@]}"
        ;;

    run)
        echo "Running in RUN mode..."

        # Validate required parameters
        if [ ! -f "$CONFIG_FILE" ]; then
            echo "ERROR: CONFIG_FILE not found at: $CONFIG_FILE"
            exit 1
        fi

        # Validate required parameters
        if [ ! -f "$KUBECONFIG" ]; then
            echo "ERROR: KUBECONFIG file not found at: $KUBECONFIG"
            exit 1
        fi

        # Build the command
        CMD="krkn_ai run --config $CONFIG_FILE --output $OUTPUT_DIR --kubeconfig $KUBECONFIG"

        # Add optional parameters
        if [ -n "$FORMAT" ]; then
            CMD="$CMD --format $FORMAT"
        fi

        if [ -n "$RUNNER_TYPE" ]; then
            CMD="$CMD --runner-type $RUNNER_TYPE"
        fi

        # Add extra parameters (comma-separated key=value pairs)
        if [ -n "$EXTRA_PARAMS" ]; then
            IFS=',' read -ra PARAMS <<< "$EXTRA_PARAMS"
            for param in "${PARAMS[@]}"; do
                CMD="$CMD --param $param"
            done
        fi

        # Add verbosity flags
        if [ "$VERBOSE" -ge 1 ]; then
            for ((i=0; i<$VERBOSE; i++)); do
                CMD="$CMD -v"
            done
        fi

        echo "Executing: $CMD"
        eval $CMD
        ;;

    *)
        echo "ERROR: Invalid MODE '$MODE'. Must be 'discover' or 'run'"
        usage
        ;;
esac

# Set permissions on output directory (best effort, may fail if directory was pre-created with different ownership)
chmod -R 777 "$OUTPUT_DIR" 2>/dev/null || echo "Warning: Could not set permissions on $OUTPUT_DIR"

echo "Execution completed!"
