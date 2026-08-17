# E-commerce platform Helm chart

This chart packages the current e-commerce baseline: Product, Cart, Order,
Inventory, Payment, Notification, the browser frontend, and a PostgreSQL
instance for the Product catalog.

## Install locally

Build the images first, then install into the active Docker Desktop Kubernetes
context:

```bash
make build-services
helm upgrade --install ecommerce-platform ./deploy/helm/ecommerce-platform
kubectl get deployment,service,pods -l app.kubernetes.io/instance=ecommerce-platform
```

The repository Make target includes `--take-ownership --force-conflicts` so an
existing deployment created from `deploy/kubernetes/*.yaml` can be adopted
during the migration to Helm.

The chart uses local images with `IfNotPresent`, so it is suitable for the
current local cluster workflow. Override image tags or replica counts with a
custom values file or `--set` when needed.

The PostgreSQL volume is a small local PVC intended for the development
cluster. The six business services use the same development PostgreSQL instance
with logically separate tables; production deployments should use separate
credentials and stronger secret management.

Open the UI with a port-forward:

```bash
kubectl port-forward service/frontend 8080:8000
```

Then visit `http://127.0.0.1:8080`.

The development realm includes `customer-1` with password
`customer-dev-password`. The frontend validates the Keycloak access token and
requires the authenticated username to match the requested cart owner.
