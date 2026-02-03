# Agentic Cloud Auditor - Minimal Deployable Version

A production-ready, minimal cloud auditing system using agentic AI patterns.

## Features

- ✅ Multi-cloud support (Azure, AWS, GCP)
- ✅ Redis-based task queue for scalability
- ✅ PostgreSQL for audit results storage
- ✅ FastAPI-based REST API
- ✅ Docker and Kubernetes ready
- ✅ Health checks and metrics
- ✅ Horizontal auto-scaling

## Quick Start

### 1. Prerequisites
```bash
# Install tools
brew install kubectl docker kind helm  # macOS
# or
apt-get install kubectl docker.io     # Ubuntu

# For Azure
az aks get-credentials --resource-group myResourceGroup --name myAKSCluster