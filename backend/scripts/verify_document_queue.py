"""Real migration/RLS/outbox + Redis/RQ Linux-process checks, with no cloud credentials.

python scripts/verify_document_queue.py [--api-image doctrace-api:rq-verify]
Builds the backend image if --api-image is omitted. All containers are disposable.
Only PDF/embedding/S3/Milvus work is replaced by queue_worker_fixture.py.
"""
import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
from redis.exceptions import ConnectionError as RedisConnectionError
from rq.command import send_kill_horse_command

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import AppConfig
from app.dispatcher import dispatch_once
from app.services.document_repository import DocumentRepository
from app.services.job_queue import DocumentQueue

ROOT = Path(__file__).resolve().parents[1]


def eventually(check, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for queue state")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-image")
    args = parser.parse_args()
    prefix = f"baymax-rq-{uuid.uuid4().hex[:10]}"
    image = args.api_image or f"{prefix}:verify"
    containers = []

    def docker(*command, check=True):
        result = subprocess.run(["docker", *command], text=True, capture_output=True, timeout=600)
        if check and result.returncode:
            raise RuntimeError(f"Docker command failed: {command}\n{result.stdout}\n{result.stderr}")
        if command[0] == "logs":
            return result.stdout + result.stderr
        return result.stdout.strip()

    def launch(suffix, *options):
        name = f"{prefix}-{suffix}"
        containers.append(name)
        docker("run", "-d", "--name", name, "--network", prefix, *options)
        return name

    def sql(statement, *, fails=False):
        result = subprocess.run(["docker", "exec", "-i", f"{prefix}-db", "psql", "-U", "postgres", "-At", "-v", "ON_ERROR_STOP=1"],
                                input=statement, text=True, capture_output=True, timeout=30)
        if fails:
            assert result.returncode, "SQL unexpectedly succeeded"
            return result.stderr
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()

    def value(statement):
        text = sql(statement)
        return json.loads(text) if text else None

    def port(name, number):
        return docker("port", name, str(number)).rsplit(":", 1)[1]

    owner, other = str(uuid.uuid4()), str(uuid.uuid4())

    def document(name="normal.pdf"):
        doc = str(uuid.uuid4())
        sql(f"insert into documents(doc_id,user_id,name,size_bytes,storage_key) values ('{doc}','{owner}','{name}',20,'{owner}/{doc}/{name}');")
        return doc

    def request(doc, kind="index"):
        return value(f"select request_document_operation('{doc}','{owner}','{kind}');")

    def operation(doc):
        return value(f"select row_to_json(o) from document_operations o join documents d on d.current_operation_id=o.operation_id where d.doc_id='{doc}';")

    def begin(op):
        return value(f"select begin_document_attempt('{op['operation_id']}',{op['delivery']},5);")

    def finish(attempt, extra=""):
        return sql(f"select finish_document_attempt('{attempt['operation_id']}','{attempt['attempt_id']}'{extra});")

    def expire(op):
        sql(f"update document_operations set attempt_expires_at=now()-interval '1 second', available_at=now() where operation_id='{op['operation_id']}';")

    def recover(op):
        token = f"'{op['attempt_id']}'" if op["attempt_id"] else "null"
        return sql(f"select recover_document_operation('{op['operation_id']}',{op['delivery']},{token});")

    queue = None
    try:
        if not args.api_image:
            print("Building isolated worker image...", flush=True)
            docker("build", "-t", image, str(ROOT))
        docker("network", "create", prefix)
        db = launch("db", "--network-alias", "db", "-e", "POSTGRES_PASSWORD=queue-test-password", "postgres:16-alpine")
        # The entrypoint's temporary initdb server accepts Unix sockets before it restarts.
        eventually(lambda: "accepting connections" in docker("exec", db, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False))
        sql("""
            create schema auth; create table auth.users(id uuid primary key);
            create role anon; create role authenticated; create role service_role bypassrls;
            create function auth.uid() returns uuid language sql stable as
            $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
            grant usage on schema auth, public to authenticated, anon, service_role;
        """)
        sql((ROOT / "migrations/001_document_library.sql").read_text())
        sql(f"insert into auth.users values('{owner}'),('{other}');")
        legacy = document()
        sql(f"select queue_document_job('{legacy}','{owner}','index');")
        old = value("select claim_document_job(120);")
        sql((ROOT / "migrations/002_rq_document_jobs.sql").read_text())
        assert old["lease_token"] in sql("select generation_id from document_generations;")
        assert "does not exist" in sql("select claim_document_job(120);", fails=True)
        assert operation(legacy)["kind"] == "index"

        # Atomic begin and fenced publication, including delivery CAS with two dispatchers.
        doc = document()
        assert "Document not found" in sql(f"select request_document_operation('{doc}','{other}','index');", fails=True)
        request(doc)
        op = operation(doc)
        with ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(lambda _: begin(op), range(2)))
        assert sum(item is not None for item in claims) == 1
        first = next(item for item in claims if item)
        expire(first)
        op = operation(doc)
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(lambda _: recover(op), range(2))) == ["f", "t"]
        second = begin(operation(doc))
        assert first["attempt_id"] != second["attempt_id"]
        assert finish(first) == "f"
        assert finish(second) == "t"
        assert finish(first, ", 'late failure', false") == "f"
        sql("update document_generations set cleanup_after=now()-interval '1 second';")
        assert second["attempt_id"] not in value(f"select document_cleanup_candidates('{doc}');")

        # User RLS and service-only RPCs.
        assert sql(f"set role authenticated; set request.jwt.claim.sub='{other}'; select count(*) from documents;").splitlines()[-1] == "0"
        assert "permission denied" in sql("set role authenticated; select * from document_operations;", fails=True)
        assert "permission denied" in sql(f"set role authenticated; select begin_document_attempt('{op['operation_id']}',0,5);", fails=True)

        # Deletion revokes publication and waits for a live superseded writer.
        deleting = document()
        request(deleting)
        writer = begin(operation(deleting))
        request(deleting, "delete")
        assert begin(operation(deleting)) is None
        assert finish(writer) == "f"
        deletion = begin(operation(deleting))
        assert finish(deletion, ", 'Storage down', false") == "f"
        assert "cannot be indexed" in sql(f"select request_document_operation('{deleting}','{owner}','index');", fails=True)
        request(deleting, "delete")
        assert finish(begin(operation(deleting))) == "t"

        # Redis loss cannot reset the durable budget, and upload recovery is independent of dequeue.
        interrupted = document()
        request(interrupted)
        for _ in range(3):
            attempt = begin(operation(interrupted))
            expire(attempt)
            assert recover(operation(interrupted)) == "t"
        assert operation(interrupted)["state"] == "failed"
        stale = document()
        sql(f"update documents set updated_at=now()-interval '16 minutes' where doc_id='{stale}'; select recover_stale_document_uploads();")
        assert sql(f"select status from documents where doc_id='{stale}';") == "error"
        sql("truncate documents cascade;")  # This entire database is disposable.
        print("PASS: migration upgrade, RLS, concurrent begin/recovery, fencing, deletion, budget", flush=True)

        redis_name = launch("redis", "--network-alias", "redis", "-p", "127.0.0.1::6379", "redis:7.4.8-alpine",
                            "redis-server", "--appendonly", "yes", "--appendfsync", "everysec", "--maxmemory-policy", "noeviction")
        secret = "disposable-postgrest-jwt-secret-at-least-32-characters"
        encode = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
        token = b".".join([encode(b'{"alg":"HS256","typ":"JWT"}'), encode(b'{"role":"service_role"}')])
        token = (token + b"." + encode(hmac.new(secret.encode(), token, hashlib.sha256).digest())).decode()
        rest = launch("rest", "--network-alias", "rest", "-p", "127.0.0.1::3000",
                      "-e", "PGRST_DB_URI=postgres://postgres:queue-test-password@db:5432/postgres",
                      "-e", "PGRST_DB_ANON_ROLE=anon", "-e", f"PGRST_JWT_SECRET={secret}", "postgrest/postgrest:v12.2.12")
        rest_url = f"http://127.0.0.1:{port(rest, 3000)}"
        eventually(lambda: docker("exec", redis_name, "redis-cli", "ping", check=False) == "PONG")
        # The real repository uses Supabase's /rest/v1 prefix; plain PostgREST serves /.
        proxy = launch("proxy", "--network-alias", "supabase", "-p", "127.0.0.1::8000", "-v", f"{ROOT / 'scripts'}:/checks:ro",
                       "-e", "PYTHONPATH=/app", image, "python", "/checks/queue_postgrest_proxy.py")
        config = AppConfig(redis_url=f"redis://127.0.0.1:{port(redis_name,6379)}/0", document_index_timeout_seconds=5,
                           supabase_url=f"http://127.0.0.1:{port(proxy,8000)}", supabase_service_role_key=token)
        repository, queue = DocumentRepository(config), DocumentQueue(config)
        def ready():
            try:
                return httpx.get(rest_url, timeout=1).status_code == 200
            except httpx.HTTPError:
                return False
        eventually(ready)

        def pump():
            asyncio.run(dispatch_once(repository, queue))

        def state(doc, expected):
            pump()
            current = asyncio.run(repository.internal_document(doc))
            return current if current["status"] == expected else None

        def worker(suffix):
            return launch(suffix, "-v", f"{ROOT / 'scripts'}:/checks:ro", "-e", "PYTHONPATH=/app",
                          "-e", "REDIS_URL=redis://redis:6379/0", "-e", "SUPABASE_URL=http://supabase:8000",
                          "-e", f"SUPABASE_SERVICE_ROLE_KEY={token}", "-e", "DOCUMENT_INDEX_TIMEOUT_SECONDS=5",
                          image, "python", "/checks/queue_worker_fixture.py")

        # Durable handoff, deduplication, persistence and an actual outage before any workers run.
        queued = document()
        request(queued)
        docker("stop", redis_name)
        try:
            pump()
            raise AssertionError("Redis outage was swallowed")
        except RedisConnectionError:
            pass
        docker("start", redis_name)
        eventually(lambda: docker("exec", redis_name, "redis-cli", "ping", check=False) == "PONG")
        queue.close()
        config.redis_url = f"redis://127.0.0.1:{port(redis_name,6379)}/0"
        queue = DocumentQueue(config)
        pump()
        queue.enqueue(operation(queued))
        assert queue.queue.count == 1
        docker("restart", redis_name)
        eventually(lambda: docker("exec", redis_name, "redis-cli", "ping", check=False) == "PONG")
        queue.close()
        config.redis_url = f"redis://127.0.0.1:{port(redis_name,6379)}/0"
        queue = DocumentQueue(config)
        assert queue.status(operation(queued)) == "queued"
        worker_one = worker("worker-one")
        worker_two = worker("worker-two")
        eventually(lambda: state(queued, "ready"))
        print("PASS: outbox Redis outage, unique delivery, AOF restart, two Linux RQ workers", flush=True)

        retrying = document("retry.pdf")
        request(retrying)
        eventually(lambda: state(retrying, "ready"))
        assert operation(retrying)["attempts"] == 2
        lost = document("lost.pdf")
        request(lost)
        ready_doc = eventually(lambda: state(lost, "ready"))
        assert queue.connection.exists(f"vectors:{ready_doc['active_index_id']}")
        invalid = document("invalid.pdf")
        request(invalid)
        eventually(lambda: state(invalid, "error"))
        assert operation(invalid)["attempts"] == 1
        print("PASS: scheduled retry, terminal input error, lost committed publish response", flush=True)

        # Delete during indexing: allow the old writer to finish and verify it cannot publish.
        slow = document("slow.pdf")
        request(slow)
        eventually(lambda: state(slow, "processing"))
        old_generation = operation(slow)["attempt_id"]
        request(slow, "delete")
        queue.connection.set(f"release:{slow}", "yes")
        queue.connection.set(f"fail-delete:{slow}", "yes")
        eventually(lambda: state(slow, "deleted"))
        assert operation(slow)["attempts"] == 2
        queue.connection.set(f"vectors:{old_generation}", owner)  # Simulate a late remote write.
        sql(f"update document_generations set cleanup_after=now()-interval '1 second' where doc_id='{slow}';")
        tombstone = asyncio.run(repository.internal_document(slow))
        queue.enqueue_cleanup(tombstone)
        eventually(lambda: not queue.connection.exists(f"vectors:{old_generation}"))
        print("PASS: delete during indexing, partial deletion retry, tombstone late-write cleanup", flush=True)

        # Kill the actual work horse. Expire the DB deadline to avoid a 65-second test wait.
        killed = document("slow.pdf")
        request(killed)
        eventually(lambda: state(killed, "processing"))
        from rq.job import Job
        job = Job.fetch(queue.job_id(operation(killed)), connection=queue.connection)
        send_kill_horse_command(queue.connection, job.worker_name)
        eventually(lambda: queue.status(operation(killed)) != "started")
        expire(operation(killed))
        queue.connection.set(f"release:{killed}", "yes")
        eventually(lambda: state(killed, "ready"))
        assert operation(killed)["attempts"] == 2

        # Remove actual queued Redis keys while workers are paused, then repair from intent.
        docker("pause", worker_one, worker_two)
        missing = document()
        request(missing)
        pump()
        missing_id = queue.job_id(operation(missing))
        queue.connection.delete(f"rq:job:{missing_id}")
        queue.connection.lrem(queue.queue.key, 0, missing_id)
        assert queue.status(operation(missing)) is None
        pump()
        assert queue.status(operation(missing)) == "queued"
        docker("unpause", worker_one, worker_two)
        eventually(lambda: state(missing, "ready"))
        # Failure before task entry: no application callback ran, dispatcher repairs metadata.
        broken = document()
        request(broken)
        queue.queue.enqueue("app.jobs.documents.missing_function", job_id=queue.job_id(operation(broken)))
        eventually(lambda: state(broken, "error"))
        assert operation(broken)["attempts"] == 0
        request(broken)
        eventually(lambda: state(broken, "ready"))

        # Kill the entire container. An idle RQ worker may still be blocked on dequeue;
        # the dispatcher must fence/replace the expired attempt despite its stale started key.
        abandoned = document("slow.pdf")
        request(abandoned)
        eventually(lambda: state(abandoned, "processing"))
        abandoned_job = Job.fetch(queue.job_id(operation(abandoned)), connection=queue.connection)
        from rq import Worker
        running = next(w for w in Worker.all(connection=queue.connection) if w.name == abandoned_job.worker_name)
        victim = next(name for name in (worker_one, worker_two)
                      if docker("inspect", "--format", "{{.Config.Hostname}}", name) == running.hostname)
        docker("kill", victim)
        expire(operation(abandoned))
        queue.connection.set(f"release:{abandoned}", "yes")
        eventually(lambda: state(abandoned, "ready"), timeout=90)
        assert operation(abandoned)["attempts"] == 2
        print("PASS: killed horse/container recovery, lost Redis keys, pre-task failure reconciliation", flush=True)
        print("All queue integration checks passed.", flush=True)
    except Exception:
        for name in containers:
            if "worker" in name or name.endswith("proxy"):
                print(docker("logs", "--tail", "50", name, check=False), flush=True)
        raise
    finally:
        if queue:
            queue.close()
        for name in reversed(containers):
            docker("rm", "-f", "-v", name, check=False)
        docker("network", "rm", prefix, check=False)
        if not args.api_image:
            docker("image", "rm", image, check=False)


if __name__ == "__main__":
    main()
