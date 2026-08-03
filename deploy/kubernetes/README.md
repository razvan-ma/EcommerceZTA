# Local Kubernetes

The project currently targets Docker Desktop's managed Kubernetes cluster in **kind mode**. The active context is `docker-desktop`.

## Start the cluster

In Docker Desktop, enable Kubernetes in **Settings → Kubernetes → Enable Kubernetes → Apply & Restart**. Confirm it is ready with:

```bash
docker desktop kubernetes status
kubectl get nodes
```

## Deploy the Product service

From the repository root:

```bash
make k8s-deploy
make k8s-status
```

The manifest uses the local image `ecommerce-zta/product:0.1.0`, which is already available to the Docker Desktop Kubernetes runtime after the image build.

## Query the service locally

In a separate terminal:

```bash
make k8s-product
```

Then query:

```bash
curl http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:8000/products
```

The port-forward remains active until interrupted with `Ctrl-C`.

