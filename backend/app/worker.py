"""python -m app.worker: standard RQ fetch/fork/execute worker with retry scheduler."""
from redis import Redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from app.core.config import get_config
from app.core.observability import configure_logging
from app.core.sentry import configure_sentry
from app.db import dispose_engines
from app.services.document_repository import DocumentRepository, read_document
from app.services.failures import flush_failures
from app.services.purges import advance_purges


class DocumentWorker(Worker):
    @property
    def dequeue_timeout(self):
        # An idle RQ worker otherwise blocks for ~405s, delaying purge/outbox
        # recovery well beyond the 30s maintenance interval.
        return min(super().dequeue_timeout, 30)

    def main_work_horse(self, job, queue):
        # Maintenance opens a parent SQL pool. A child must never reuse its
        # inherited sockets or close connections still owned by the parent.
        dispose_engines(close=False)
        return super().main_work_horse(job, queue)

    def handle_job_failure(self, job, queue, started_job_registry=None, exc_string=""):
        # RQ persists its formatted exception separately from console logging.
        # SDK/SQL errors can contain document content or credentials there too.
        result = super().handle_job_failure(
            job, queue, started_job_registry=started_job_registry,
            exc_string="Document job failed; consult structured logs by job_id.",
        )
        # Reconcile terminal timeouts/abandoned jobs, including failures that
        # never reached the child task's exception handler. Never read job text.
        if job.func_name in ("app.jobs.documents.index_document", "app.jobs.documents.delete_document"):
            try:
                doc = read_document(self.connection, job.args[0])
                if doc and doc.get("job_id") == job.id:
                    DocumentRepository(get_config()).get_sync(doc["workspace_id"], doc["owner_user_id"], doc["doc_id"])
            except Exception:
                self.log.warning("failure_persistence_failed")
        flush_failures(get_config())
        return result

    def run_maintenance_tasks(self):
        super().run_maintenance_tasks()
        flush_failures(get_config())
        advance_purges(get_config())


def main() -> None:
    config = get_config()
    configure_logging(config, install_root=True)
    configure_sentry(config)
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
