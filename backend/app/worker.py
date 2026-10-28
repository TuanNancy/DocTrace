"""python -m app.worker: standard RQ fetch/fork/execute worker with retry scheduler."""
from redis import Redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from app.core.config import get_config
from app.core.observability import configure_logging


class DocumentWorker(Worker):
    def handle_job_failure(self, job, queue, started_job_registry=None, exc_string=""):
        # RQ persists its formatted exception separately from console logging.
        # SDK/SQL errors can contain document content or credentials there too.
        return super().handle_job_failure(
            job, queue, started_job_registry=started_job_registry,
            exc_string="Document job failed; consult structured logs by job_id.",
        )


def main() -> None:
    config = get_config()
    configure_logging(config, install_root=True)
    # RQ sets its own blocking socket timeout. Do not reuse the producer's short timeout.
    connection = Redis.from_url(config.redis_url, socket_connect_timeout=5)
    try:
        queue = Queue(config.rq_queue_name, connection=connection, serializer=JSONSerializer)
        worker = DocumentWorker([queue], connection=connection, serializer=JSONSerializer, maintenance_interval=30)
        worker.work(with_scheduler=True)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
