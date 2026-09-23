# Deployment

- The API runs as a stateless Python service on Kubernetes.
- Replica count is managed by a HorizontalPodAutoscaler: **minimum 3, maximum
  24 replicas**. During the daily batch window (01:00–03:00 UTC) it routinely
  sits at 20+; overnight it drops back to 3. Pods are also replaced on every
  deploy (several times a day) and on node rotation.
- Ingress is an **L4 load balancer doing round-robin** across ready pods.
  There is **no session affinity**: consecutive requests from the same API key
  land on different pods (the LB has no visibility of the API key — it sits in
  the `Authorization` header, inside TLS terminated at the pod).
- Pods have no stable identity and no local persistent volume. Anything held
  in process memory is lost on restart/scale-in.
- Clock skew between nodes is kept under 50 ms by chrony.
