"""Isolated Redis catalog + Linux RQ integration; no PostgreSQL or cloud credentials.

python scripts/verify_document_queue.py [--api-image doctrace-api:verify]
Builds a disposable image if omitted. PDF/AI/S3/Milvus are replaced by fixtures.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import time
import uuid

from fastapi import HTTPException
from redis import Redis
from rq import Worker
from rq.command import send_kill_horse_command
from rq.job import Job
from rq.registry import StartedJobRegistry
from rq.scheduler import RQScheduler
from rq.serializers import JSONSerializer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import AppConfig
from app.services.document_repository import DocumentRepository, document_key, catalog_key
from app.services.job_queue import DocumentQueue

ROOT = Path(__file__).resolve().parents[1]


def eventually(check, timeout=90):
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
    prefix = f"doctrace-rq-{uuid.uuid4().hex[:10]}"
    image = args.api_image or f"{prefix}:verify"
    containers = []
    connection = None

    def docker(*command, check=True):
        result = subprocess.run(["docker", *command], text=True, capture_output=True, timeout=600)
        if check and result.returncode:
            raise RuntimeError(f"Docker command failed: {command}\n{result.stdout}\n{result.stderr}")
        return result.stdout + result.stderr if command[0] == "logs" else result.stdout.strip()

    def launch(suffix, *options):
        name = f"{prefix}-{suffix}"
        containers.append(name)
        docker("run", "-d", "--name", name, "--network", prefix, *options)
        return name

    owner = str(uuid.uuid4())
    config = AppConfig(document_index_timeout_seconds=5)
    repository = DocumentRepository(config)
    run = asyncio.run

    def document(name="normal.pdf"):
        doc_id = str(uuid.uuid4())
        return run(repository.create({"doc_id": doc_id, "user_id": owner, "name": name,
                                      "size_bytes": 20, "storage_key": f"{owner}/{doc_id}/{name}"}))

    def current(record):
        return run(repository.internal_document(record["doc_id"]))

    def state(record, expected):
        item = run(repository.get(owner, record["doc_id"]))
        return item if item["status"] == expected else None

    def finished(record):
        return queue.status(current(record)["job_id"]) == "finished"

    def started(record):
        item = current(record)
        return item if item["attempt_number"] > 0 and connection.exists(f"started:{record['doc_id']}") else None

    def expect_status(code, action):
        try:
            action()
        except HTTPException as exc:
            assert exc.status_code == code, exc
        else:
            raise AssertionError(f"Expected HTTP {code}")

    try:
        docker("info")
        if not args.api_image:
            print("Building isolated worker image...", flush=True)
            docker("build", "-t", image, str(ROOT))
        docker("network", "create", prefix)
        redis_name = launch("redis", "--network-alias", "redis", "-p", "127.0.0.1::6379", "redis:7.4.8-alpine",
                            "redis-server", "--appendonly", "yes", "--appendfsync", "everysec", "--maxmemory-policy", "noeviction")

        def connect():
            nonlocal connection, queue
            eventually(lambda: docker("exec", redis_name, "redis-cli", "ping", check=False) == "PONG")
            if connection:
                connection.close()
            port = docker("port", redis_name, "6379").rsplit(":", 1)[1]
            config.redis_url = f"redis://127.0.0.1:{port}/0"
            connection = Redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=5)
            queue = DocumentQueue(config, connection)

        queue = None
        connect()
        queued = document()
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: run(repository.create(queued)), range(2)))
        assert queue.queue.count == 1
        assert connection.ttl(document_key(queued["doc_id"])) == -1
        assert connection.ttl(catalog_key(owner)) == -1
        expect_status(404, lambda: run(repository.get("other", queued["doc_id"])))
        expect_status(404, lambda: run(repository.queue("other", queued["doc_id"], "delete")))
        assert run(repository.list("other", 100, 0))["items"] == []
        expect_status(409, lambda: run(repository.queue(owner, queued["doc_id"], "delete")))

        docker("stop", redis_name)
        expect_status(503, lambda: run(repository.check_available()))
        expect_status(503, lambda: document())
        docker("start", redis_name)
        connect()
        assert queue.queue.count == 1
        assert state(queued, "queued")
        print("PASS: atomic catalog/enqueue, duplicate request, owner scope, outage and AOF restart", flush=True)

        def worker(suffix):
            return launch(suffix, "-v", f"{ROOT / 'tests' / 'fixtures'}:/checks:ro", "-e", "PYTHONPATH=/app",
                          "-e", "REDIS_URL=redis://redis:6379/0", "-e", f"RQ_QUEUE_NAME={config.rq_queue_name}",
                          "-e", "DOCUMENT_INDEX_TIMEOUT_SECONDS=5", image, "python", "/checks/queue_worker.py")

        workers = [worker("worker-one"), worker("worker-two")]
        eventually(lambda: state(queued, "ready"))
        eventually(lambda: finished(queued))
        connection.delete(Job.key_for(queued["job_id"]))  # Simulate expiration of RQ's result record.
        assert state(queued, "ready")
        assert run(repository.list(owner, 100, 0))["items"]

        retrying = document("retry.pdf")
        eventually(lambda: state(retrying, "ready"))
        assert current(retrying)["attempt_number"] == 2
        old, active = current(retrying)["generations"]
        assert not connection.exists(f"vectors:{old}")
        assert connection.exists(f"vectors:{active}")
        lost = document("lost.pdf")
        ready = eventually(lambda: state(lost, "ready"))
        assert connection.exists(f"vectors:{ready['active_index_id']}")
        invalid = document("invalid.pdf")
        eventually(lambda: state(invalid, "error"))
        eventually(lambda: finished(invalid))
        assert current(invalid)["attempt_number"] == 1
        timed_out = document("timeout.pdf")
        eventually(lambda: state(timed_out, "ready"))
        assert current(timed_out)["attempt_number"] == 2
        print("PASS: real Linux workers, scheduled retry, timeout, invalid PDF, lost publication reply, result expiry", flush=True)

        slow = document("slow.pdf")
        eventually(lambda: started(slow))
        expect_status(409, lambda: run(repository.queue(owner, slow["doc_id"], "delete")))
        connection.set(f"release:{slow['doc_id']}", "yes")
        eventually(lambda: state(slow, "ready"))
        eventually(lambda: finished(slow))
        connection.set(f"fail-delete:{slow['doc_id']}", "yes")
        deleting = run(repository.queue(owner, slow["doc_id"], "delete"))
        assert deleting["active_index_id"] is None
        eventually(lambda: current(slow)["status"] == "deleted")
        assert current(slow)["attempt_number"] == 2
        assert not any(connection.exists(f"vectors:{generation}") for generation in current(slow)["generations"])
        expect_status(404, lambda: run(repository.get(owner, slow["doc_id"])))
        print("PASS: busy deletion rejected, partial deletion retry, catalog removal", flush=True)

        killed = document("slow.pdf")
        eventually(lambda: started(killed))
        running_job = Job.fetch(killed["job_id"], connection=connection, serializer=JSONSerializer)
        send_kill_horse_command(connection, running_job.worker_name)
        eventually(lambda: queue.status(killed["job_id"]) != "started")
        connection.set(f"release:{killed['doc_id']}", "yes")
        eventually(lambda: state(killed, "ready"))
        assert current(killed)["attempt_number"] == 2

        docker("pause", *workers)
        missing = document()
        connection.delete(Job.key_for(missing["job_id"]))
        connection.lrem(queue.queue.key, 0, missing["job_id"])
        assert state(missing, "error")
        run(repository.queue(owner, missing["doc_id"], "index"))
        broken = document()
        broken_job = Job.fetch(broken["job_id"], connection=connection, serializer=JSONSerializer)
        broken_job.func_name = "app.jobs.documents.missing_function"
        broken_job.retries_left = 0
        broken_job.save()
        docker("unpause", *workers)
        eventually(lambda: state(missing, "ready"))
        eventually(lambda: state(broken, "error"))
        assert current(broken)["attempt_number"] == 0
        run(repository.queue(owner, broken["doc_id"], "index"))
        eventually(lambda: state(broken, "ready"))
        eventually(lambda: finished(broken))

        # Kill the scheduler's worker deliberately, rather than passing only when
        # the other worker happens to consume this job.
        scheduler_key = RQScheduler.get_locking_key(config.rq_queue_name)
        scheduler_owner = connection.get(scheduler_key)
        scheduler = RQScheduler.fetch(scheduler_owner.decode(), connection=connection)
        victim = next(name for name in workers if docker("inspect", "--format", "{{.Config.Hostname}}", name) == scheduler.hostname)
        survivors = [name for name in workers if name != victim]
        # Stop idle consumers so Redis cannot deliver the job to a paused
        # worker's still-open blocking dequeue connection.
        docker("stop", *survivors)
        abandoned = document("slow.pdf")
        eventually(lambda: started(abandoned))
        abandoned_job = Job.fetch(abandoned["job_id"], connection=connection, serializer=JSONSerializer)
        running = next(w for w in Worker.all(connection=connection) if w.name == abandoned_job.worker_name)
        assert running.hostname == scheduler.hostname
        docker("kill", victim)
        connection.set(f"release:{abandoned['doc_id']}", "yes")
        # Advance RQ's registry clock after the process is dead, avoiding a full
        # heartbeat expiry wait. This is the real abandoned-job maintenance path.
        StartedJobRegistry(config.rq_queue_name, connection=connection, serializer=JSONSerializer).cleanup(time.time() + 120)
        # RQ's killed scheduler retains its ~61s lease. Restart after expiry (or
        # takeover): an earlier restart can enter a 405s idle dequeue before its
        # next maintenance pass, longer than this test's 90s deadline.
        print("Waiting for killed scheduler lease expiry/takeover...", flush=True)
        eventually(lambda: connection.get(scheduler_key) != scheduler_owner)
        docker("start", victim, *survivors)
        eventually(lambda: state(abandoned, "ready"))
        assert current(abandoned)["attempt_number"] == 2
        print("PASS: killed horse/container/scheduler, missing job keys, pre-task failure and manual retry", flush=True)
        print("All Redis/RQ integration checks passed.", flush=True)
    except Exception:
        for name in containers:
            if "worker" in name:
                print(docker("logs", "--tail", "50", name, check=False), flush=True)
        raise
    finally:
        if connection:
            connection.close()
        for name in reversed(containers):
            docker("rm", "-f", "-v", name, check=False)
        if containers:
            docker("network", "rm", prefix, check=False)
        if not args.api_image:
            docker("image", "rm", image, check=False)


if __name__ == "__main__":
    main()
