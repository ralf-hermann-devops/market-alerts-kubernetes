import base64
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIRECTORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TESTS_DIRECTORY))

from job_runner import kubectl, alert_count


NAMESPACE = "trading-alerts"
TRAEFIK_NAMESPACE = "traefik"
TRAEFIK_SERVICE = "service/traefik"
HOSTNAME = "alerts.example.invalid"
WEBHOOK_PATH = "/webhook/tradingview"
PORT_FORWARD_PORT = int(os.environ.get("HTTPS_WEBHOOK_PORT", "18443"))
PORT_FORWARD_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 15


def secret_value(secret_name: str, key: str) -> bytes:
    """Read and decode a value from a Kubernetes Secret."""
    
    encoded = kubectl("get", "secret", secret_name,
                    "--namespace",NAMESPACE,
                    f"--output=jsonpath={{.data.{key}}}",
                    capture_output=True,
    )
    if not encoded:
        raise RuntimeError(f"Secret {secret_name!r} has no value for key {key!r}")
    return base64.b64decode(encoded)


def wait_for_port_forward(process: subprocess.Popen[bytes]) -> None:
    """Wait until kubectl has opened the local forwarded port."""
    deadline = time.monotonic() + PORT_FORWARD_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"kubectl port-forward exited with status {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", PORT_FORWARD_PORT), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(
        f"Traefik port-forward did not open port {PORT_FORWARD_PORT} "
        f"within {PORT_FORWARD_TIMEOUT_SECONDS} seconds"
    )


class ForwardedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the forwarded address while preserving the ingress SNI name."""

    
    def __init__( self,
                    *,
                    connect_host: str,
                    server_hostname: str,
                    port: int,
                    context: ssl.SSLContext) -> None:
        super().__init__(
            server_hostname,
            port,
            timeout=REQUEST_TIMEOUT_SECONDS,
            context=context)
        self._connect_host = connect_host
        self._server_hostname = server_hostname

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_host, self.port), self.timeout
        )
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self._server_hostname
        )


def send_webhook(ca_certificate: bytes, webhook_secret: bytes) -> None:
    """Send one authenticated webhook through Traefik over verified HTTPS."""
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=ca_certificate.decode("ascii"))
    payload = json.dumps(
        {
            "secret": webhook_secret.decode(),
            "symbol": "AAPL",
            "action": "long",
            "price": 123.45,
            "timeframe": "1h",
        }
    ).encode()

    connection = ForwardedHTTPSConnection(
        connect_host="127.0.0.1",
        server_hostname=HOSTNAME,
        port=PORT_FORWARD_PORT,
        context=context)
    
    try:
        connection.request(
            "POST",
            WEBHOOK_PATH,
            body=payload,
            headers={
                "Content-Type": "application/json",
                "Host": HOSTNAME,
            },
        )
        response = connection.getresponse()
        response_body = response.read().decode()
    finally:
        connection.close()

    # Check 1: Verify that the HTTPS webhook returned the expected HTTP status code.
    if response.status != 202:
        raise RuntimeError(
            f"HTTPS webhook returned HTTP {response.status} {response.reason}: "
            f"{response_body}"
        )
    print(f"HTTPS webhook returned HTTP {response.status} {response.reason}.")


def main() -> int:
    """Forward Traefik HTTPS locally and verify the public webhook route."""
    port_forward = None
    try:
        ca_certificate = secret_value("local-ca-key-pair", r"tls\.crt")
        webhook_secret = secret_value("trading-alerts-secrets", "webhook-secret")
        print(
            f"Starting port-forward for {TRAEFIK_SERVICE} "
            f"on localhost:{PORT_FORWARD_PORT}."
        )
        port_forward = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                f"--namespace={TRAEFIK_NAMESPACE}",
                TRAEFIK_SERVICE,
                f"{PORT_FORWARD_PORT}:443",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        alerts_before = alert_count()
        wait_for_port_forward(port_forward)
        send_webhook(ca_certificate, webhook_secret)
        alerts_after = alert_count()

        # Check 2: Verify that the alert count increased after sending the webhook.
        if alerts_after <= alerts_before:
            print("Alert count did not increase after sending webhook.", file=sys.stderr)
            return 1
        else:
            print("Alert count increased after sending webhook.")        
            return 0
        
    except FileNotFoundError as error:
        print(f"Required command not found: {error.filename}", file=sys.stderr)
        return 1
    except (RuntimeError, TimeoutError, OSError, subprocess.CalledProcessError) as error:
        print(f"HTTPS webhook smoke test failed: {error}", file=sys.stderr)
        return 1
    finally:
        if port_forward is not None and port_forward.poll() is None:
            port_forward.terminate()
            try:
                port_forward.wait(timeout=5)
            except subprocess.TimeoutExpired:
                port_forward.kill()
                port_forward.wait()


if __name__ == "__main__":
    raise SystemExit(main())
