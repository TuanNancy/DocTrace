"""RQ adapter; callers share a Redis transaction with library metadata writes."""
from redis import Redis
from rq import Queue, Retry
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.serializers import JSONSerializer

from app.core.config import AppConfig

LIVE_STATES = {"queued", "started", "scheduled", "deferred"}


class DocumentQueue:
    def __init__(self, config: AppConfig, connection: Redis):
        self.config = config
        self.connection = connection
        self.queue = Queue(config.rq_queue_name, connection=connection, serializer=JSONSerializer)

    def status(self, job_id: str | None) -> str | None:
        if not job_id:
            return None
        try:
            return Job.fetch(job_id, connection=self.connection,
                             serializer=JSONSerializer).get_status(refresh=False).value
        except NoSuchJobError:
            return None  # Connection failures must propagate, not look like missing jobs.

    def enqueue(self, doc_id: str, job_id: str, kind: str, pipeline) -> None:
        timeout = (self.config.document_index_timeout_seconds if kind == "index"
                   else self.config.document_delete_timeout_seconds)
        # RQ 2.12 unique=True ignores the supplied pipeline. The repository's WATCH
        # guards the document instead, so metadata and enqueue commit together.
        self.queue.enqueue_call(
            f"app.jobs.documents.{kind}_document", args=(doc_id,), job_id=job_id,
            pipeline=pipeline, timeout=timeout, retry=Retry(max=2, interval=[10, 30]),
            result_ttl=86400, failure_ttl=604800,
        )
