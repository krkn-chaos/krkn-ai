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

When running the workflow manually, choose `krkn-ai`,
`krkn-ai-operator`, or `both` in the **Image to build and push** input. The
same `tag` input is used for the selected image.

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

### Results storage for `KrknAIRun`

- `shared` (default) creates one retained claim. It defaults to
  `ReadWriteMany`; set `aiOrchestrator.storage.storageClassName` to an
  RWX-capable class or set `aiOrchestrator.storage.existingClaim` to a
  pre-created claim. `ReadWriteOnce` is only suitable when runs are serialized.
- `dedicated` creates one controller-owned claim per run. It defaults to
  `ReadWriteOnce`, so it works with EBS classes such as `gp3-csi`. Configure
  `aiOrchestrator.storage.accessMode` when a different mode is required.

Installation defaults are configured with:

```yaml
aiOrchestrator:
  storage:
    mode: dedicated
    storageClassName: gp3-csi
    accessMode: ReadWriteOnce
    size: 5Gi
```

Run-level `spec.storage` settings override those defaults. Set `pvcName` to
mount an exact pre-existing claim without changing or owning it:

```yaml
spec:
  storage:
    pvcName: my-results-pvc
```

Without `pvcName`, setting `storageClassName`, `accessMode`, or `size` creates
a dedicated claim for that run. Without `spec.storage`, the installation mode
is used. Do not combine `pvcName` with dynamic-claim fields.

All operator runs write to `/output/<KrknAIRun.metadata.uid>/`. The selected
claim name is recorded in `.status.pvcName`. Shared and user-managed claims
survive run deletion; controller-created dedicated claims and their results
are deleted with the run.
