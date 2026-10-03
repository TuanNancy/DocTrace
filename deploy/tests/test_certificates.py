"""POSIX orchestration tests with a fake docker CLI; no certificate issuance."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "certificates.sh"


class CertificateCommandsTest(unittest.TestCase):
    def invoke(self, action, fail_match=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "commands"
            docker = root / "docker"
            docker.write_text(
                '#!/bin/sh\n'
                'printf "%s | %s\\n" "${TLS_MODE:-default}" "$*" >> "$TEST_LOG"\n'
                'case "$*" in *"$FAIL_MATCH"*) [ -z "$FAIL_MATCH" ] || exit 1 ;; esac\n'
                'exit 0\n'
            )
            docker.chmod(0o755)
            result = subprocess.run(["sh", str(SCRIPT), action], env={
                **os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                "TEST_LOG": str(log), "FAIL_MATCH": fail_match,
            }, text=True, capture_output=True)
            commands = log.read_text() if log.exists() else ""
            return result.returncode, commands

    def test_bootstrap_only_overrides_mode_for_its_command(self):
        code, commands = self.invoke("bootstrap")
        self.assertEqual(code, 0)
        self.assertTrue(commands.startswith("http |"))
        self.assertIn("up -d --build --wait api worker dispatcher nginx", commands)

    def test_issue_enables_tls_only_after_success(self):
        code, commands = self.invoke("issue")
        self.assertEqual(code, 0)
        lines = commands.splitlines()
        self.assertIn("certbot /opt/doctrace/issue.sh", lines[0])
        self.assertTrue(lines[1].startswith("https |"))
        self.assertIn("nginx -t", lines[2])
        self.assertIn("nginx -s reload", lines[3])

    def test_failed_issue_does_not_switch_or_reload_nginx(self):
        code, commands = self.invoke("issue", "/opt/doctrace/issue.sh")
        self.assertNotEqual(code, 0)
        self.assertNotIn("up -d", commands)
        self.assertNotIn("reload", commands)

    def test_failed_renewal_does_not_reload_nginx(self):
        code, commands = self.invoke("renew", "certbot renew")
        self.assertNotEqual(code, 0)
        self.assertNotIn("nginx -t", commands)
        self.assertNotIn("reload", commands)

    def test_invalid_nginx_config_does_not_reload(self):
        code, commands = self.invoke("renew", "nginx -t")
        self.assertNotEqual(code, 0)
        self.assertNotIn("nginx -s reload", commands)

    def test_successful_renewal_checks_config_then_reloads(self):
        code, commands = self.invoke("renew")
        self.assertEqual(code, 0)
        lines = commands.splitlines()
        self.assertIn("certbot renew --non-interactive", lines[0])
        self.assertIn("nginx -t", lines[1])
        self.assertIn("nginx -s reload", lines[2])


if __name__ == "__main__":
    unittest.main()
