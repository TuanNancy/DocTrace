"""Real Git checkouts and release state, fake Docker/HTTPS; no production access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy.sh"

FAKE_COMMAND = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"command": name, "args": args,
                          "project": os.environ.get("COMPOSE_PROJECT_NAME"),
                          "image": os.environ.get("API_IMAGE")}) + "\n")
failure = os.environ.get("FAIL_COMMAND", "")
if failure and failure in " ".join([name, *args]):
    raise SystemExit(1)
if name == "curl":
    print('{"status":"ok"}')
elif name == "docker":
    if args[0] == "compose":
        command = args[7:]  # --project-directory, --env-file, -f
        if (command[0] == "config" and os.environ.get("FAIL_CONFIG_WITH_RELEASE_FILE")
                and (Path(os.environ["DEPLOY_ROOT"]) / "release.txt").exists()):
            raise SystemExit("Invalid Compose configuration in this release")
        if command == ["config", "--format", "json"]:
            print(json.dumps({"name": "existing-project", "services": {"nginx": {"environment": {
                "API_DOMAIN": "api.example.test", "TLS_MODE": os.environ.get("FAKE_TLS", "https")}}}}))
        elif command[:3] == ["ps", "--all", "--quiet"]:
            if not os.environ.get("NO_CONTAINERS"):
                print(command[3] + "-container")
        elif command[0] == "up" and command[-2:] == ["api", "worker"]:
            image = os.environ["API_IMAGE"]
            state["api"] = state["worker"] = state["images"][image]
    elif args[0] == "inspect":
        print(state[args[-1].removesuffix("-container")])
    elif args[:2] == ["image", "tag"]:
        state["images"][args[3]] = args[2]
    elif args[:2] == ["image", "inspect"]:
        if args[2] not in state["images"]:
            raise SystemExit(1)
        print("[]")
    elif args[0] == "build":
        tag = args[args.index("--tag") + 1]
        state["images"][tag] = "sha256:" + tag.rsplit("sha-", 1)[-1]
state_path.write_text(json.dumps(state))
'''


@unittest.skipUnless(shutil.which("flock"), "Deployment requires Linux flock (run on Ubuntu/Docker)")
class DeploymentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.origin = self.root / "origin"
        self.origin.mkdir()
        self.env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
        # Isolate from any developer Compose settings.
        for key in ("API_IMAGE", "COMPOSE_PROJECT_NAME", "DEPLOY_ROOT", "DEPLOY_ENV_FILE"):
            self.env.pop(key, None)
        self.git(self.origin, "init", "--initial-branch=main")
        self.git(self.origin, "config", "user.email", "ci@example.test")
        self.git(self.origin, "config", "user.name", "Deployment test")
        (self.origin / ".gitignore").write_text(".env.production\nbackend/.env\n")
        (self.origin / "compose.production.yml").write_text("services: {}\n")
        (self.origin / "backend").mkdir()
        (self.origin / "backend/Dockerfile").write_text("FROM scratch\n")
        self.old = self.commit("initial deployed version")
        (self.origin / "deploy").mkdir()
        shutil.copyfile(SCRIPT, self.origin / "deploy/deploy.sh")
        self.new = self.commit("add CD")
        (self.origin / "release.txt").write_text("newest\n")
        self.latest = self.commit("next release")
        self.checkout = self.root / "vps"
        self.git(self.root, "clone", str(self.origin), str(self.checkout))
        self.git(self.checkout, "checkout", "--detach", self.old)
        self.production_env = self.checkout / ".env.production"
        self.production_env.write_text("# Keep this comment\nAPI_DOMAIN=api.example.test\nTLS_MODE=https\nAPI_IMAGE=doctrace-api:local\n")
        (self.checkout / "backend/.env").write_text("PRIVATE_SENTINEL=unchanged\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("docker", "curl", "sleep"):
            executable = self.bin / name
            executable.write_text(FAKE_COMMAND)
            executable.chmod(0o755)
        self.log = self.root / "commands.jsonl"
        self.fake_state = self.root / "docker.json"
        self.initial_image = "sha256:" + "a" * 64
        self.retained = "doctrace-api:retained-" + "a" * 64
        self.fake_state.write_text(json.dumps({
            "api": self.initial_image, "worker": self.initial_image,
            "images": {"doctrace-api:local": self.initial_image},
        }))
        self.env.update({
            "PATH": f"{self.bin}:{self.env['PATH']}", "DEPLOY_ROOT": str(self.checkout),
            "FAKE_LOG": str(self.log), "FAKE_STATE": str(self.fake_state),
        })
        self.state = self.checkout / ".git/doctrace-deploy"

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              text=True, capture_output=True).stdout.strip()

    def commit(self, message):
        self.git(self.origin, "add", ".")
        self.git(self.origin, "commit", "-m", message)
        return self.git(self.origin, "rev-parse", "HEAD")

    def invoke(self, *args, success=True, script=SCRIPT, **env):
        result = subprocess.run(["bash", str(script), *args], env={**self.env, **env},
                                text=True, capture_output=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def release(self, name):
        return (self.state / name).read_text().strip().split()

    def test_exact_commit_and_persistent_image_preserve_existing_project_and_secrets(self):
        # Origin is ahead: deploy the tested SHA, not origin/main's latest commit.
        self.invoke("deploy", self.new)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.new)
        self.assertEqual(self.release("current"), [self.new, f"doctrace-api:sha-{self.new}"])
        self.assertEqual(self.release("previous"), [self.old, self.retained])
        self.assertIn(f"API_IMAGE=doctrace-api:sha-{self.new}\n", self.production_env.read_text())
        self.assertIn("# Keep this comment", self.production_env.read_text())
        self.assertEqual((self.checkout / "backend/.env").read_text(), "PRIVATE_SENTINEL=unchanged\n")
        self.assertFalse((self.state / "pending").exists())
        updates = [c for c in self.commands() if "up" in c["args"]]
        self.assertEqual(len(updates), 2)
        self.assertTrue(all(c["project"] == "existing-project" for c in updates))
        self.assertIn("--no-build", updates[0]["args"])
        self.assertIn("--force-recreate", updates[1]["args"])
        self.assertTrue(any(c["command"] == "curl" for c in self.commands()))

    def test_rollback_reuses_image_even_to_a_commit_without_deploy_script(self):
        self.invoke("deploy", self.new)
        self.log.write_text("")
        self.invoke("rollback", script=self.state / "recover.sh")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.old)
        self.assertEqual(self.release("current"), [self.old, self.retained])
        self.assertFalse((self.checkout / "deploy/deploy.sh").exists())
        self.assertIn(f"API_IMAGE={self.retained}", self.production_env.read_text())
        self.assertFalse(any(c["args"][0] == "build" for c in self.commands()))

    def test_health_failure_keeps_last_good_release_and_can_recover(self):
        self.invoke("deploy", self.new)
        self.invoke("deploy", self.latest, success=False, FAIL_COMMAND="curl")
        self.assertEqual(self.release("current")[0], self.new)
        self.assertTrue((self.state / "pending").exists())
        self.invoke("deploy", self.latest, success=False)
        self.invoke("rollback", script=self.state / "recover.sh")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.new)
        self.assertFalse((self.state / "pending").exists())

    def test_build_failure_never_recreates_services_and_first_release_can_recover(self):
        original_env = self.production_env.read_text()
        self.invoke("deploy", self.new, success=False, FAIL_COMMAND="docker build")
        self.assertFalse(any("up" in c["args"] for c in self.commands()))
        self.assertEqual(self.production_env.read_text(), original_env)
        self.assertEqual(self.release("current"), [self.old, self.retained])
        self.invoke("rollback", script=self.state / "recover.sh")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.old)

    def test_rollback_can_restore_a_checkout_whose_compose_config_cannot_resolve(self):
        self.invoke("deploy", self.new)
        self.invoke("deploy", self.latest, success=False, FAIL_CONFIG_WITH_RELEASE_FILE="1")
        self.assertEqual(self.release("current")[0], self.new)
        self.invoke("rollback", script=self.state / "recover.sh", FAIL_CONFIG_WITH_RELEASE_FILE="1")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.new)
        self.assertFalse((self.state / "pending").exists())

    def test_missing_rq_registration_fails_even_if_api_is_healthy(self):
        self.invoke("deploy", self.new, success=False, FAIL_COMMAND="exec -T worker python -")
        self.assertEqual(self.release("current")[0], self.old)
        self.assertTrue((self.state / "pending").exists())

    def test_stale_ci_run_cannot_replace_newer_release(self):
        self.invoke("deploy", self.latest)
        self.log.write_text("")
        result = self.invoke("deploy", self.new)
        self.assertIn("Skipping stale", result.stdout)
        self.assertFalse(any("up" in c["args"] or "build" in c["args"] for c in self.commands()))
        self.assertEqual(self.release("current")[0], self.latest)

    def test_rerun_does_not_overwrite_an_existing_commit_image(self):
        self.invoke("deploy", self.new)
        self.log.write_text("")
        self.invoke("deploy", self.new)
        self.assertFalse(any(c["args"][0] == "build" for c in self.commands()))
        self.assertEqual(self.release("previous"), [self.old, self.retained])

    def test_dirty_checkout_is_preserved(self):
        path = self.checkout / "backend/Dockerfile"
        path.write_text("local edit\n")
        self.invoke("deploy", self.new, success=False)
        self.assertEqual(path.read_text(), "local edit\n")
        self.assertFalse(self.commands())

    def test_untracked_collision_is_not_overwritten(self):
        path = self.checkout / "release.txt"
        path.write_text("local work\n")
        self.invoke("deploy", self.latest, success=False)
        self.assertEqual(path.read_text(), "local work\n")
        self.assertFalse(any("up" in c["args"] for c in self.commands()))

    def test_no_containers_and_http_mode_cannot_bootstrap_new_volumes(self):
        self.invoke("deploy", self.new, success=False, NO_CONTAINERS="1")
        self.invoke("deploy", self.new, success=False, FAKE_TLS="http")
        self.assertFalse(any("up" in c["args"] for c in self.commands()))

    def test_invalid_revision_is_rejected(self):
        self.invoke("deploy", "main; echo unsafe", success=False)
        self.assertFalse(self.commands())

    def test_host_lock_prevents_overlapping_manual_deploys(self):
        import fcntl

        self.state.mkdir(parents=True)
        with (self.state / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.invoke("deploy", self.new, success=False)
        self.assertFalse(self.commands())


if __name__ == "__main__":
    unittest.main()
