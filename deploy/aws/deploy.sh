#!/usr/bin/env bash
# Deploy the app to the EKS cluster and RDS database created by deploy/terraform.
#
#   deploy/aws/deploy.sh            # build + push image, install the chart, print the URL
#   deploy/aws/deploy.sh --measure  # also run scripts/aws_measure.py -> results/aws_deploy.json
#
# Needs: aws (logged in), terraform (applied), docker, kubectl, helm. Credentials come from the
# AWS CLI's login session; Terraform's provider reads them through `aws configure export-credentials`.
set -euo pipefail
cd "$(dirname "$0")/../.."

PROFILE="${AWS_PROFILE:-console}"
REGION="${AWS_REGION:-us-east-2}"
NAMESPACE=grocery
RELEASE=grocery

export AWS_PROFILE="$PROFILE" AWS_REGION="$REGION"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
IMAGE="$ECR/grocery-optimizer"
TAG=$(git rev-parse --short HEAD)

CLUSTER=$(terraform -chdir=deploy/terraform output -raw cluster_name)
DB_ENDPOINT=$(terraform -chdir=deploy/terraform output -raw postgres_endpoint)
SECRET_ARN=$(terraform -chdir=deploy/terraform output -raw postgres_password_secret_arn)

echo "== image $IMAGE:$TAG"
aws ecr describe-repositories --repository-names grocery-optimizer >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name grocery-optimizer >/dev/null
aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR" >/dev/null
# The cluster nodes are x86_64; build for that platform even from an Apple Silicon laptop.
docker build --platform linux/amd64 -t "$IMAGE:$TAG" .
docker push "$IMAGE:$TAG"

echo "== kubeconfig for $CLUSTER"
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" >/dev/null
kubectl get nodes

echo "== database secret"
# RDS generated the master password into Secrets Manager; it goes straight into a Kubernetes
# Secret and never into a file or a shell history line.
DB_PASS=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])')
DB_USER=$(terraform -chdir=deploy/terraform output -raw database_url_template | sed -E 's#.*://([^:]+):.*#\1#')
DB_NAME=$(terraform -chdir=deploy/terraform output -raw database_url_template | sed 's#.*/##')
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$NAMESPACE" create secret generic grocery-optimizer-secrets \
  --from-literal=DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASS@$DB_ENDPOINT/$DB_NAME" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
unset DB_PASS

echo "== helm"
helm upgrade --install "$RELEASE" deploy/helm/grocery-optimizer -n "$NAMESPACE" \
  --set image.repository="$IMAGE" --set image.tag="$TAG" --set image.pullPolicy=IfNotPresent \
  --set secret.existingSecret=grocery-optimizer-secrets \
  --set persistence.enabled=false \
  --set replicaCount=2 \
  --set service.type=LoadBalancer \
  --wait --timeout 10m
kubectl -n "$NAMESPACE" get pods -o wide

echo "== waiting for the load balancer hostname"
for _ in $(seq 60); do
  HOST=$(kubectl -n "$NAMESPACE" get svc "$RELEASE-grocery-optimizer" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  [ -n "$HOST" ] && break
  sleep 5
done
echo "URL: http://$HOST"

if [ "${1:-}" = "--measure" ]; then
  python3 scripts/aws_measure.py --url "http://$HOST" --out results/aws_deploy.json \
    --namespace "$NAMESPACE" --release "$RELEASE" --region "$REGION" --cluster "$CLUSTER"
fi
