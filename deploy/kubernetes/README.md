# Local Kubernetes

The project currently targets Docker Desktop's managed Kubernetes cluster in **kind mode**. The active context is `docker-desktop`.

## Start the cluster

In Docker Desktop, enable Kubernetes in **Settings → Kubernetes → Enable Kubernetes → Apply & Restart**. Confirm it is ready with:

```bash
docker desktop kubernetes status
kubectl get nodes
```

## Build and deploy the services

From the repository root:

```bash
make build-services
make k8s-deploy
make k8s-status
```

The manifests use the local images `ecommerce-zta/product:0.1.0`, `ecommerce-zta/cart:0.1.0`, and `ecommerce-zta/order:0.1.0`, which are available to the Docker Desktop Kubernetes runtime after the image builds.

## Query the service locally

In a separate terminal:

```bash
kubectl port-forward service/product 8001:8000
kubectl port-forward service/cart 8002:8000
kubectl port-forward service/order 8003:8000
```

Use separate terminals for the port-forwards. The Product, Cart, and Order APIs are then available on ports `8001`, `8002`, and `8003` respectively.

Then query:

```bash
curl http://127.0.0.1:8001/health/ready
curl http://127.0.0.1:8001/products
curl http://127.0.0.1:8002/carts/customer-1
curl http://127.0.0.1:8003/orders
```

The port-forward remains active until interrupted with `Ctrl-C`.
