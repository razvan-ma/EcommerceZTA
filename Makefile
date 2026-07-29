.PHONY: install test run-product build-product deploy-product

install:
	python3 -m pip install -r requirements-dev.txt

test:
	python3 -m pytest

run-product:
	python3 -m uvicorn services.product.app.main:app --reload --port 8000

build-product:
	docker build -t ecommerce-zta/product:0.1.0 services/product

deploy-product:
	kubectl apply -f deploy/kubernetes/product.yaml

