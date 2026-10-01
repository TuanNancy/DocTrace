"""Docker integration checks for the production Nginx templates; no cloud credentials.

Run from any directory: python deploy/tests/verify_nginx.py --api-image doctrace-api:verify
Build that API image first. All containers/volumes use a random, disposable project.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-image", default="doctrace-api:verify")
    args = parser.parse_args()
    project = "doctrace-nginx-test-" + uuid.uuid4().hex[:10]
    env = {
        **os.environ,
        "API_DOMAIN": "api.example.test", "ACME_EMAIL": "ci@example.test", "TLS_MODE": "http",
        "BACKEND_ENV_FILE": str(ROOT / "deploy/tests/api.env"), "API_IMAGE": args.api_image,
        "NGINX_BIND_ADDRESS": "127.0.0.1", "NGINX_HTTP_PORT": "0", "NGINX_HTTPS_PORT": "0",
    }
    base = [
        "docker", "compose", "--project-name", project, "--project-directory", str(ROOT),
        "--env-file", str(ROOT / ".env.production.example"),
        "-f", str(ROOT / "compose.production.yml"), "-f", str(ROOT / "deploy/tests/compose.test.yml"),
    ]

    def dc(*command, check=True):
        result = subprocess.run(base + list(command), env=env, text=True, capture_output=True, timeout=180)
        if check and result.returncode:
            raise RuntimeError(f"Compose {' '.join(command)} failed:\n{result.stdout}\n{result.stderr}")
        return result

    def port(number):
        return int(dc("port", "nginx", str(number)).stdout.strip().rsplit(":", 1)[1])

    def request(number, path, context=None, method="GET", headers=None, body=None):
        connection = (http.client.HTTPSConnection("127.0.0.1", number, context=context, timeout=5)
                      if context else http.client.HTTPConnection("127.0.0.1", number, timeout=5))
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def eventually(check):
        deadline = time.monotonic() + 25
        while True:
            try:
                if check():
                    return
            except (OSError, http.client.HTTPException):
                pass
            if time.monotonic() >= deadline:
                raise AssertionError("Timed out waiting for proxy state")
            time.sleep(0.2)

    def certificate(*options):
        return dc("run", "--rm", "--entrypoint", "python", "certbot", "/checks/make_certificate.py", *options).stdout

    try:
        missing = dc("run", "--rm", "--no-deps", "-e", "TLS_MODE=https", "nginx", check=False)
        assert missing.returncode != 0 and "TLS certificate missing" in missing.stderr
        print("PASS: HTTPS refuses to start without certificates")

        certificate("challenge")
        dc("up", "-d", "--no-build", "--wait", "api", "nginx")
        http_port = port(80)
        assert request(http_port, "/.well-known/acme-challenge/probe")[2] == b"challenge-value"
        assert request(http_port, "/.well-known/acme-challenge/missing")[0] == 404
        assert request(http_port, "/health")[0] == 503
        print("PASS: bootstrap serves ACME challenges but not the API")

        context = ssl.create_default_context(cadata=certificate())
        env["TLS_MODE"] = "https"
        dc("up", "-d", "--no-build", "--wait", "nginx")
        dc("exec", "-T", "nginx", "nginx", "-t")
        http_port, https_port = port(80), port(443)
        status, headers, _ = request(http_port, "/health?x=1", headers={"Host": "untrusted.example"})
        assert status == 308 and headers["Location"] == "https://api.example.test/health?x=1"
        assert request(http_port, "/.well-known/acme-challenge/probe")[0] == 200
        assert json.loads(request(https_port, "/health", context)[2]) == {"status": "ok"}
        print("PASS: trusted TLS, fixed-host HTTP redirect and live API health")

        status, _, body = request(https_port, "/__probe", context, headers={
            "Authorization": "Bearer proxy-test-token", "X-Forwarded-For": "203.0.113.123",
            "X-Forwarded-Proto": "http", "Host": "api.example.test",
        })
        probe = json.loads(body)
        assert status == 200 and probe["authorization"] == "Bearer proxy-test-token"
        assert probe["scheme"] == "https" and probe["forwarded_for"] != "203.0.113.123"
        assert probe["host"] == "api.example.test"
        preflight = request(https_port, "/api/chat", context, method="OPTIONS", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        assert preflight[0] == 200 and preflight[1]["access-control-allow-origin"] == "http://localhost:3000"
        print("PASS: bearer/CORS forwarding and spoofed forwarding-header protection")

        connection = http.client.HTTPSConnection("127.0.0.1", https_port, context=context, timeout=5)
        connection.putrequest("POST", "/api/upload")
        connection.putheader("Content-Length", str(56 * 1024 * 1024))
        connection.endheaders()
        assert connection.getresponse().status == 413
        connection.close()
        print("PASS: oversized upload rejected before sending its body")

        def open_stream():
            connection = http.client.HTTPSConnection("127.0.0.1", https_port, context=context, timeout=5)
            connection.request("POST", "/api/chat", body=json.dumps({"query": "q", "doc_id": "doc"}), headers={
                "Authorization": "Bearer proxy-test-token", "Content-Type": "application/json",
            })
            response = connection.getresponse()
            assert response.status == 200 and "text/event-stream" in response.getheader("content-type")
            received = b""
            while b'data: "first"\n\n' not in received:
                line = response.readline()
                assert line, "Stream ended before the first token"
                received += line
            assert b"event: sources" in received
            return connection, response

        connection, response = open_stream()
        request(https_port, "/__release", context, method="POST")
        remainder = response.read()
        assert b'"last"' in remainder and b'event: done\ndata: "[DONE]"' in remainder
        response.close()
        connection.close()
        eventually(lambda: json.loads(request(https_port, "/__probe", context)[2])["active"] == 0)
        print("PASS: SSE reaches the client before upstream completion")

        connection, response = open_stream()
        response.close()
        connection.close()
        eventually(lambda: json.loads(request(https_port, "/__probe", context)[2])["active"] == 0)
        print("PASS: client disconnect cancels the upstream SSE request")

        context = ssl.create_default_context(cadata=certificate())
        dc("exec", "-T", "nginx", "nginx", "-t")
        dc("exec", "-T", "nginx", "nginx", "-s", "reload")
        eventually(lambda: request(https_port, "/health", context)[0] == 200)
        print("PASS: graceful reload serves the rotated certificate")

        nginx_id = dc("ps", "-q", "nginx").stdout.strip()
        dc("up", "-d", "--no-build", "--force-recreate", "--wait", "api")
        eventually(lambda: request(https_port, "/health", context)[0] == 200)
        assert dc("ps", "-q", "nginx").stdout.strip() == nginx_id
        print("PASS: API recreation recovers without restarting Nginx")
    except BaseException:
        logs = dc("logs", "--tail=60", "api", "nginx", check=False)
        print(logs.stdout, logs.stderr)
        raise
    finally:
        # Only this invocation's randomly named project and test volumes are removed.
        dc("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
