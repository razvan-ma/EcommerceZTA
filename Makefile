.PHONY: install test run-product build-product build-cart build-order build-inventory build-payment build-notification build-frontend build-services deploy-product k8s-context k8s-status k8s-deploy k8s-product helm-template helm-deploy

install:
	python3 -m pip install -r requirements-dev.txt

test:
	python3 -m pytest

run-product:
	python3 -m uvicorn services.product.app.main:app --reload --port 8000

build-product:
	docker build -t ecommerce-zta/product:0.2.0 services/product

build-cart:
	docker build -t ecommerce-zta/cart:0.2.1 services/cart

build-order:
	docker build -t ecommerce-zta/order:0.2.1 services/order

build-inventory:
	docker build -t ecommerce-zta/inventory:0.2.0 services/inventory

build-payment:
	docker build -t ecommerce-zta/payment:0.2.0 services/payment

build-notification:
	docker build -t ecommerce-zta/notification:0.2.0 services/notification

build-frontend:
	docker build -t ecommerce-zta/frontend:0.2.0 services/frontend

build-services: build-product build-cart build-order build-inventory build-payment build-notification build-frontend

deploy-product:
	kubectl apply -f deploy/kubernetes/product.yaml

k8s-context:
	kubectl config use-context docker-desktop

k8s-status:
	kubectl get nodes
	kubectl get deployment,service,pods -l 'app in (product,cart,order,inventory,payment,notification)'

k8s-deploy: k8s-context
	kubectl apply -f deploy/kubernetes/product.yaml
	kubectl apply -f deploy/kubernetes/inventory.yaml
	kubectl apply -f deploy/kubernetes/cart-order.yaml
	kubectl apply -f deploy/kubernetes/payment-notification.yaml
	kubectl rollout status deployment/product --timeout=120s
	kubectl rollout status deployment/inventory --timeout=120s
	kubectl rollout status deployment/payment --timeout=120s
	kubectl rollout status deployment/notification --timeout=120s
	kubectl rollout status deployment/order --timeout=120s
	kubectl rollout status deployment/cart --timeout=120s

k8s-product:
	kubectl port-forward service/product 8000:8000

helm-template:
	helm template ecommerce-platform ./deploy/helm/ecommerce-platform

helm-deploy: k8s-context
	# These flags support migration from existing kubectl-managed manifests.
	helm upgrade --install ecommerce-platform ./deploy/helm/ecommerce-platform --take-ownership --force-conflicts
