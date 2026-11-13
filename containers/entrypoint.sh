#!/bin/bash
set -e
child_pid=
termination_signal=

forward_signal() {
    local signal_name="$1"
    termination_signal="$signal_name"
    if [ -n "$child_pid" ]; then
        kill -"$signal_name" "$child_pid" 2>/dev/null || true
    fi
}

run_command() {
    "$@" &
    child_pid=$!
    if [ -n "$termination_signal" ]; then
        kill -"$termination_signal" "$child_pid" 2>/dev/null || true
    fi
    local command_status=0
    while true; do
        if wait "$child_pid"; then
            command_status=0
        else
            command_status=$?
        fi
        if ! kill -0 "$child_pid" 2>/dev/null; then
            break
        fi
    done
    child_pid=
    return "$command_status"
}

write_completion_marker() {
    local exit_code=$?
    trap - EXIT
    if [ -n "${KRKNAI_RUN_UID:-}" ] && [ -n "${OUTPUT_DIR:-}" ]; then
        local run_output_dir="$OUTPUT_DIR/$KRKNAI_RUN_UID"
        if mkdir -p "$run_output_dir"; then
            local outcome="failed"
            if [ -f "$run_output_dir/results.json" ]; then
                outcome="$(python -c 'import json,sys; status=json.load(open(sys.argv[1])).get("status"); print("succeeded" if status in ("completed", "succeeded") else "cancelled" if status == "cancelled" else "failed")' "$run_output_dir/results.json" 2>/dev/null)" || outcome="failed"
            fi
            if [ "$exit_code" -ne 0 ] && [ "$outcome" != "cancelled" ]; then
                outcome="failed"
            fi
            local marker="$run_output_dir/.krkn-ai-complete"
            local temporary_marker="$marker.$$"
            if printf '{"exitCode":%d,"outcome":"%s"}\n' "$exit_code" "$outcome" > "$temporary_marker"; then
                mv -f "$temporary_marker" "$marker"
            else
                rm -f "$temporary_marker"
            fi
        fi
    fi
    exit "$exit_code"
}

# The uploader sidecar waits for this marker before committing artifacts.
# Record the run outcome atomically without masking the runner's exit code.
trap write_completion_marker EXIT
trap 'forward_signal TERM' TERM
trap 'forward_signal INT' INT

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
    echo "  Optional: OUTPUT_DIR, FORMAT, RUNNER_TYPE, EXTRA_PARAMS, VERBOSE, KRKNAI_RUN_UID"
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
        if [ -n "${KRKNAI_OPERATOR_REGISTRY_NAME:-}" ]; then
            CMD+=(--operator-registry-name "$KRKNAI_OPERATOR_REGISTRY_NAME")
        fi

        # Add optional parameters
        if [ -n "$NAMESPACE" ]; then
            CMD+=(--namespace "$NAMESPACE")
        fi
        if [ -n "$POD_LABEL" ]; then
            CMD+=(--pod-label "$POD_LABEL")
        fi
        if [ -n "$NODE_LABEL" ]; then
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
        run_command "${CMD[@]}"
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

        # Build the command array
        CMD=(krkn_ai run --config "$CONFIG_FILE" --output "$OUTPUT_DIR" --kubeconfig "$KUBECONFIG")
        if [ -n "${KRKNAI_OPERATOR_REGISTRY_NAME:-}" ]; then
            CMD+=(--operator-registry-name "$KRKNAI_OPERATOR_REGISTRY_NAME")
        fi
        if [ -n "$KRKNAI_RUN_UID" ]; then
            CMD+=(--run-uuid "$KRKNAI_RUN_UID")
        fi

        # Add optional parameters
        if [ -n "$FORMAT" ]; then
            CMD+=(--format "$FORMAT")
        fi

        if [ -n "$RUNNER_TYPE" ]; then
            CMD+=(--runner-type "$RUNNER_TYPE")
        fi

        # Add extra parameters (comma-separated key=value pairs)
        if [ -n "$EXTRA_PARAMS" ]; then
            IFS=',' read -ra PARAMS <<< "$EXTRA_PARAMS"
            for param in "${PARAMS[@]}"; do
                CMD+=(--param "$param")
            done
        fi

        # Add verbosity flags
        if [ "$VERBOSE" -ge 1 ]; then
            for ((i=0; i<$VERBOSE; i++)); do
                CMD+=(-v)
            done
        fi

        echo "Executing: ${CMD[*]}"
        run_command "${CMD[@]}"
        ;;

    *)
        echo "ERROR: Invalid MODE '$MODE'. Must be 'discover' or 'run'"
        usage
        ;;
esac

# Set permissions on the run's output directory (best effort). Operator runs
# use their stable child directory so a shared results volume is not recursed.
PERMISSION_TARGET="$OUTPUT_DIR"
if [ -n "$KRKNAI_RUN_UID" ]; then
    PERMISSION_TARGET="$OUTPUT_DIR/$KRKNAI_RUN_UID"
fi
chmod -R 777 "$PERMISSION_TARGET" 2>/dev/null || echo "Warning: Could not set permissions on $PERMISSION_TARGET"

echo "Execution completed!"
