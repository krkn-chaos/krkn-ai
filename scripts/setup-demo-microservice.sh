#!/bin/bash

#******************************************************************************
# File: setup-demo-microservice.sh
# Author: Rahul Shetty (Perf & Scale)
# Date: 2025-05-05
#
# Description:
# This script sets up a sample robot-shop micro-service based app on K8s cluster.
#
#
# Usage:
# ./setup-demo-microservice.sh
#
# Pre-requisite:
# - kubectl and oc client
# - User should be already logged into cluster before running the script
#
#******************************************************************************

# Define variables
chart_name="robot-shop"
repo_url="https://github.com/instana/robot-shop/" # Replace with the actual Helm repo URL
namespace="${DEMO_NAMESPACE:-robot-shop}" # Replace with the desired namespace if not default
repo_dir="temp-helm-repo"
helm_chart="K8s/helm"
is_openshift="${IS_OPENSHIFT:-true}" # TODO: Automatically detect if the cluster is openshift or not
image_repo="mirror.gcr.io/robotshop"
infra_registry="mirror.gcr.io/library" # mirror for Docker Hub official images (redis, rabbitmq)

# Create a temporary directory
temp_dir="./tmp"
mkdir -p $temp_dir

# Trap for exit signals and errors
trap cleanup EXIT

cleanup() {
  echo "Script finished."
}

# Switch to the temporary directory
cd "$temp_dir"
echo "Switched to directory: $PWD"

if [ -d "$repo_dir" ]; then
  echo "Directory '$repo_dir' already exists. Skipping cloning."
else
    # Clone repository
    echo "Directory '$repo_dir' does not exist. Cloning repository..."
    git clone --depth 1 --branch master $repo_url $repo_dir
fi

cd $repo_dir
echo "Switched to cloned directory: $PWD"

# Setup Namespace
kubectl get ns $namespace || kubectl create ns $namespace

if [ "$is_openshift" = "true" ]; then
    # Based on https://github.com/instana/robot-shop/tree/master/OpenShift
    oc adm new-project $namespace
    oc adm policy add-scc-to-user anyuid -z default -n $namespace
    oc adm policy add-scc-to-user privileged -z default -n $namespace
fi

# Post-renderer to redirect hardcoded redis/rabbitmq images to the mirror registry
post_renderer=$(mktemp)
cat > "$post_renderer" << POSTRENDER
#!/bin/bash
sed "s|image: redis:|image: ${infra_registry}/redis:|g
     s|image: rabbitmq:|image: ${infra_registry}/rabbitmq:|g"
POSTRENDER
chmod +x "$post_renderer"

# Install Helm Chart
cd $helm_chart
helm upgrade -i $chart_name \
  --set openshift="$is_openshift" \
  --set image.repo="$image_repo" \
  --post-renderer "$post_renderer" \
  --namespace "$namespace" .
echo "Installed helm chart '$chart_name' in namespace '$namespace'"

rm -f "$post_renderer"
