# HTTPS webhook

The on-premise Kubernetes overlay serves the TradingView webhook through HTTPS
and redirects HTTP requests to HTTPS. It is configured for the reserved
placeholder hostname:

```text
alerts.example.invalid
```

`example.invalid` is intentionally not a public DNS name. It cannot be used by
TradingView and must be replaced before exposing the service publicly.

## Local Kubernetes use

The bootstrap installs cert-manager before the application overlay. The
on-premise overlay creates:

- a self-signed cluster issuer;
- a local certificate-authority certificate in the `local-ca-key-pair` Secret;
- a namespace-scoped issuer based on that CA; and
- the `api-tls` Secret used by the API Ingress.

After bootstrapping the cluster, wait for certificate issuance:

```powershell
kubectl wait --for=condition=Ready certificate/local-ca --namespace trading-alerts --timeout=120s
kubectl wait --for=condition=Ready certificate/api-tls --namespace trading-alerts --timeout=120s
```

Map the placeholder name to the externally reachable address of Traefik. For
example, when Traefik is reachable on the local machine:

```text
127.0.0.1 alerts.example.invalid
```

Add that mapping to the Windows hosts file at
`C:\Windows\System32\drivers\etc\hosts` from an elevated editor. For kind or
Minikube, use the IP address or port-forwarding approach appropriate to the
cluster rather than assuming `127.0.0.1`.

Export the local CA certificate:

```powershell
$ca = kubectl get secret local-ca-key-pair --namespace trading-alerts `
  --output='jsonpath={.data.tls\.crt}'
[IO.File]::WriteAllBytes(
  "$env:TEMP\market-alerts-local-ca.crt",
  [Convert]::FromBase64String($ca)
)
```

Import the exported CA certificate into the trusted root certificate store for
the client that calls the webhook. On Windows, open the certificate file and
install it in **Local Computer > Trusted Root Certification Authorities**.
Only trust this CA on development machines you control.

Test the redirect and HTTPS endpoint:

```powershell
curl.exe -I http://alerts.example.invalid/webhook/tradingview
curl.exe --cacert "$env:TEMP\market-alerts-local-ca.crt" `
  https://alerts.example.invalid/webhook/tradingview
```

The first command should return a redirect to HTTPS. The second can return
`405 Method Not Allowed` because the webhook only accepts `POST`; that still
confirms TLS and routing work.

## Public TradingView deployment

Before configuring TradingView, complete all of the following:

1. Register or choose a real public domain, for example
   `alerts.your-domain.example`.
2. Create a public DNS record for that name pointing to the Internet-facing
   load balancer or ingress IP.
3. Replace every occurrence of `alerts.example.invalid` in:
   - `k8s/manifests/base/apps/api/ingress.yaml`
   - `k8s/manifests/overlays/on-premise/local-tls.yaml`
   - `k8s/manifests/overlays/on-premise/api-ingress-tls-patch.yaml`
4. Replace the local issuer in `local-tls.yaml` with an ACME issuer such as a
   Let's Encrypt `ClusterIssuer`. Configure the issuer's notification email
   and HTTP-01 or DNS-01 challenge method.
5. Update the `api-tls` `Certificate` to use the ACME issuer and remove the
   local CA resources from the public deployment.
6. Ensure inbound TCP ports 80 and 443 reach Traefik. Port 80 is still needed
   for an HTTP-01 certificate challenge and redirects all normal requests to
   HTTPS.
7. Verify certificate issuance with:

   ```powershell
   kubectl describe certificate api-tls --namespace trading-alerts
   ```

8. Test with a public network before entering the HTTPS webhook URL in
   TradingView.

Do not bypass certificate validation, use a self-signed certificate, or use a
private DNS name for TradingView. TradingView must be able to reach a
publicly trusted HTTPS endpoint.
