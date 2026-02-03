.PHONY: help build push deploy test clean local-up local-down logs

# Variables
REGISTRY ?= ghcr.io/your-org
TAG ?= latest
NAMESPACE = cloud-audit

help:
	@echo "Available commands:"
	@echo "  build         - Build Docker images"
	@echo "  push          - Push images to registry"
	@echo "  deploy        - Deploy to Kubernetes"
	@echo "  test          - Run tests"
	@echo "  clean         - Remove deployments"
	@echo "  local-up      - Start local development"
	@echo "  local-down    - Stop local development"
	@echo "  logs          - View logs"

build:
	docker build -t audit-orchestrator:$(TAG) ./orchestrator
	docker build -t audit-worker:$(TAG) ./worker

push: build
	docker tag audit-orchestrator:$(TAG) $(REGISTRY)/audit-orchestrator:$(TAG)
	docker tag audit-worker:$(TAG) $(REGISTRY)/audit-worker:$(TAG)
	docker push $(REGISTRY)/audit-orchestrator:$(TAG)
	docker push $(REGISTRY)/audit-worker:$(TAG)

deploy:
	kubectl apply -f manifests/namespace.yaml
	kubectl apply -f manifests/redis.yaml
	kubectl apply -f manifests/postgres.yaml
	@echo "Waiting for databases to be ready..."
	kubectl wait --for=condition=ready pod -l app=redis -n $(NAMESPACE) --timeout=60s
	kubectl wait --for=condition=ready pod -l app=postgres -n $(NAMESPACE) --timeout=60s
	kubectl apply -f manifests/orchestrator.yaml
	kubectl apply -f manifests/worker.yaml
	@echo "Deployment complete!"
	@echo "Orchestrator URL: http://localhost:8000"
	@echo "To port-forward: kubectl port-forward svc/orchestrator 8000:8000 -n $(NAMESPACE)"

test:
	curl -f http://localhost:8000/health || echo "Orchestrator not running"
	@echo "Testing worker connection..."
	kubectl exec deployment/worker -n $(NAMESPACE) -c worker -- python -c "import redis; r=redis.Redis(host='redis', port=6379); print('Redis:', r.ping())"

clean:
	kubectl delete -f manifests/ --ignore-not-found=true
	kubectl delete namespace $(NAMESPACE) --ignore-not-found=true

local-up:
	docker-compose up -d
	@echo "Services starting..."
	@echo "Orchestrator: http://localhost:8000"
	@echo "Redis: localhost:6379"
	@echo "PostgreSQL: localhost:5432"

local-down:
	docker-compose down -v

logs:
	docker-compose logs -f

# Database operations
db-init:
	kubectl exec deployment/postgres -n $(NAMESPACE) -c postgres -- psql -U audituser -d auditdb -c "\dt"

db-shell:
	kubectl exec -it deployment/postgres -n $(NAMESPACE) -c postgres -- psql -U audituser -d auditdb

# Port forwarding
port-forward:
	kubectl port-forward svc/orchestrator 8000:8000 -n $(NAMESPACE) &
	kubectl port-forward svc/redis 6379:6379 -n $(NAMESPACE) &
	kubectl port-forward svc/postgres 5432:5432 -n $(NAMESPACE) &
	@echo "Port forwarding active. Press Ctrl+C to stop."

# Create test audit
test-audit:
	curl -X POST http://localhost:8000/audit \
		-H "Content-Type: application/json" \
		-d '{"cloud_provider": "azure", "subscription_id": "test", "checks": ["security"]}'