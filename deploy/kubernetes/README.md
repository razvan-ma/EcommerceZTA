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

Alternatively, install the packaged baseline with Helm:

```bash
make build-services
make helm-deploy
```

The chart is located at `deploy/helm/ecommerce-platform`. It preserves the
service names and local image tags used by the raw manifests, so existing
service-to-service URLs continue to work.

The Helm deployment also starts PostgreSQL for the Product catalog and exposes
the browser UI. Forward it with:

```bash
kubectl port-forward service/frontend 8080:8000
```

Then visit `http://127.0.0.1:8080`.

Sign in with the development Keycloak account:

```text
Username: customer-1
Password: customer-dev-password
```

The frontend validates the access token and rejects requests for another
customer's cart.

The manifests use the local images `ecommerce-zta/product:0.1.0`, `ecommerce-zta/cart:0.1.1`, `ecommerce-zta/order:0.1.2`, and `ecommerce-zta/inventory:0.1.1`, which are available to the Docker Desktop Kubernetes runtime after the image builds.

## Query the service locally

In a separate terminal:

```bash
kubectl port-forward service/product 8001:8000
kubectl port-forward service/cart 8002:8000
kubectl port-forward service/order 8003:8000
kubectl port-forward service/inventory 8004:8000
kubectl port-forward service/payment 8005:8000
kubectl port-forward service/notification 8006:8000
```

Use separate terminals for the port-forwards. The Product, Cart, Order, Inventory, Payment, and Notification APIs are then available on ports `8001` through `8006` respectively.

Then query:

```bash
curl http://127.0.0.1:8001/health/ready
curl http://127.0.0.1:8001/products
curl http://127.0.0.1:8002/carts/customer-1
curl http://127.0.0.1:8003/orders
curl http://127.0.0.1:8004/inventory
curl http://127.0.0.1:8005/authorizations
curl http://127.0.0.1:8006/notifications
```

The port-forward remains active until interrupted with `Ctrl-C`.
