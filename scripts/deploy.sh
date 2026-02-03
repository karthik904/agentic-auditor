#!/bin/bash
# scripts/deploy.sh

set -e  # Exit on error

echo "🚀 Deploying Agentic Cloud Auditor..."

# Check for required tools
command -v kubectl >/dev/null 2>&1 || { echo "kubectl required but not installed. Aborting." >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker required but not installed. Aborting." >&2; exit 1; }

# Build images
echo "📦 Building Docker images..."
docker build -t audit-orchestrator:latest ./orchestrator
docker build -t audit-worker:latest ./worker

# Load images to kind (if using kind)
# kind load docker-image audit-orchestrator:latest audit-worker:latest

# Create namespace
echo "🏗️  Creating namespace..."
kubectl apply -f manifests/namespace.yaml

# Deploy databases
echo "🗄️  Deploying Redis..."
kubectl apply -f manifests/redis.yaml

echo "🗄️  Deploying PostgreSQL..."
kubectl apply -f manifests/postgres.yaml

# Wait for databases
echo "⏳ Waiting for databases to be ready..."
kubectl wait --for=condition=ready pod -l app=redis -n cloud-audit --timeout=120s
kubectl wait --for=condition=ready pod -l app=postgres -n cloud-audit --timeout=120s

# Initialize database
echo "📊 Initializing database..."
kubectl cp init.sql cloud-audit/$(kubectl get pod -l app=postgres -n cloud-audit -o jsonpath='{.items[0].metadata.name}'):/tmp/init.sql
kubectl exec deployment/postgres -n cloud-audit -c postgres -- psql -U audituser -d auditdb -f /tmp/init.sql

# Deploy applications
echo "🚀 Deploying orchestrator..."
kubectl apply -f manifests/orchestrator.yaml

echo "👷 Deploying workers..."
kubectl apply -f manifests/worker.yaml

# Wait for applications
echo "⏳ Waiting for applications to be ready..."
sleep 10
kubectl wait --for=condition=ready pod -l app=orchestrator -n cloud-audit --timeout=120s
kubectl wait --for=condition=ready pod -l app=worker -n cloud-audit --timeout=120s

# Display status
echo ""
echo "✅ Deployment Complete!"
echo ""
echo "📊 Status:"
kubectl get pods -n cloud-audit

echo ""
echo "🌐 Access:"
echo "  Orchestrator API: kubectl port-forward svc/orchestrator 8000:8000 -n cloud-audit"
echo "  Then visit: http://localhost:8000/docs"
echo ""
echo "📈 Metrics:"
echo "  kubectl top pods -n cloud-audit"
echo ""
echo "📋 Quick test:"
echo "  curl http://localhost:8000/health"