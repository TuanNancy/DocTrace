"""Test-only Supabase /rest/v1 prefix adapter in front of real PostgREST."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client


class Proxy(BaseHTTPRequestHandler):
    def do_GET(self):
        connection = http.client.HTTPConnection("rest", 3000, timeout=10)
        try:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            connection.request(self.command, self.path.removeprefix("/rest/v1"), body,
                               {key: value for key, value in self.headers.items() if key.lower() != "host"})
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            connection.close()

    do_POST = do_PATCH = do_GET

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 8000), Proxy).serve_forever()
