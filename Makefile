.PHONY: install test run-product build-product build-cart build-order build-services deploy-product k8s-context k8s-status k8s-deploy k8s-product

install:
	python3 -m pip install -r requirements-dev.txt

test:
	python3 -m pytest

run-product:
	python3 -m uvicorn services.product.app.main:app --reload --port 8000

build-product:
	docker build -t ecommerce-zta/product:0.1.0 services/product

build-cart:
	docker build -t ecommerce-zta/cart:0.1.0 services/cart

build-order:
	docker build -t ecommerce-zta/order:0.1.0 services/order

build-services: build-product build-cart build-order

deploy-product:
	kubectl apply -f deploy/kubernetes/product.yaml

k8s-context:
	kubectl config use-context docker-desktop

k8s-status:
	kubectl get nodes
	kubectl get deployment,service,pods -l 'app in (product,cart,order)'

k8s-deploy: k8s-context
	kubectl apply -f deploy/kubernetes/product.yaml
	kubectl apply -f deploy/kubernetes/cart-order.yaml
	kubectl rollout status deployment/product --timeout=120s
	kubectl rollout status deployment/order --timeout=120s
	kubectl rollout status deployment/cart --timeout=120s

k8s-product:
	kubectl port-forward service/product 8000:8000
