### Dedicated operator image

The operator runner does not invoke a local container runtime. Build the
dedicated image to avoid shipping Podman, `krknctl`, or `oc` in the
orchestrator image:

```bash
podman build \
  -f containers/Containerfile.operator \
  -t quay.io/krkn-chaos/krkn-ai-operator:<tag> \
  .
podman push quay.io/krkn-chaos/krkn-ai-operator:<tag>
```

The GitHub Actions image workflow publishes the same tag as
`quay.io/krkn-chaos/krkn-ai-operator:<tag>` and optionally also publishes
`quay.io/krkn-chaos/krkn-ai-operator:latest`.

`Containerfile.operator` uses Python 3.12, the locked `uv` environment, and
the existing `containers/entrypoint.sh`. It is intended for `MODE=run` with
`RUNNER_TYPE=operator`; discovery mode and the local HUB/CLI runners belong
to the full `Containerfile` image.

### Manual operator execution

Manual execution can run from the host or from any container that has access
to the Kubernetes API. The target cluster must already have the
`krkn-operator` `KrknScenarioRun` CRD and the caller must be allowed to
create, read, and delete `KrknScenarioRun` objects.

Set the operator-runner context:

```bash
export KUBECONFIG=/path/to/kubeconfig
export KRKNAI_NAMESPACE=krkn-operator
export KRKNAI_RUN_NAME=manual-run
export KRKNAI_RUN_UID=$(uuidgen)
export KRKNAI_TARGET_REQUEST_ID=self
export KRKNAI_PROVIDER=krkn-operator
export KRKNAI_CLUSTER=self
export KRKNAI_SCENARIO_MAX_RETRIES=0
```

Run directly from a source checkout:

```bash
uv run krkn_ai run \
  --config ./tmp/krkn-ai.yaml \
  --kubeconfig "$KUBECONFIG" \
  --output ./tmp/operator-results \
  --runner-type operator
```

The executor first tries in-cluster authentication and falls back to the
kubeconfig supplied to `--kubeconfig`, so the same command works inside or
outside Kubernetes. Each generated child CR is labeled
`krkn.dev/ai-run=manual-run`. Because this example uses a generated UID
without a parent `KrknAIRun`, delete the child resources explicitly after
the run.

### Run the dedicated image manually

Mount the config and kubeconfig into the paths used by the image. This image
does not require `--privileged`, a Podman socket, or nested containers:

```bash
mkdir -p ./tmp/operator-results
podman run --rm \
  -v ./tmp:/input:Z \
  -v ./tmp/operator-results:/output:Z \
  -e MODE=run \
  -e CONFIG_FILE=/input/krkn-ai.yaml \
  -e KUBECONFIG=/input/kubeconfig.yaml \
  -e KRKNAI_NAMESPACE=krkn-operator \
  -e KRKNAI_RUN_NAME=manual-run \
  -e KRKNAI_RUN_UID="$(uuidgen)" \
  -e KRKNAI_TARGET_REQUEST_ID=self \
  -e KRKNAI_PROVIDER=krkn-operator \
  -e KRKNAI_CLUSTER=self \
  -e KRKNAI_SCENARIO_MAX_RETRIES=0 \
  -e VERBOSE=2 \
  quay.io/krkn-chaos/krkn-ai-operator:<tag>
```

The container reads the kubeconfig using the Kubernetes Python client and
creates the scenario pods through `krkn-operator`; it does not run the
scenario image itself.

### Operator image in a `KrknAIRun`

For the controller-managed workflow, set the operator chart's
`images.aiOrchestrator.image` value to the dedicated image:

```bash
helm upgrade --install krkn-operator /path/to/krkn-operator/charts/krkn-operator \
  -n krkn-operator --create-namespace \
  --set images.aiOrchestrator.image=quay.io/krkn-chaos/krkn-ai-operator:<tag>
```

The controller mounts `krkn-ai.yaml` and the target kubeconfig, sets
`RUNNER_TYPE=operator`, and supplies the `KRKNAI_*` variables automatically.
Use the `KrknAIRun` and target Secret procedure in
[`../hack/README.md`](../hack/README.md) for a complete cluster test.
