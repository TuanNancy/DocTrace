"""The only Redis/RQ adapter. Payloads contain IDs; PDF bytes stay in Storage."""
from uuid import NAMESPACE_URL, uuid5

from redis import Redis
from rq import Queue, Retry
from rq.exceptions import DuplicateJobError, NoSuchJobError
from rq.job import Job
from rq.serializers import JSONSerializer

from app.core.config import AppConfig


class DocumentQueue:
    def __init__(self, config: AppConfig):
        self.config = config
        self.connection = Redis.from_url(config.redis_url, socket_connect_timeout=5, socket_timeout=10)
        self.queue = Queue(config.rq_queue_name, connection=self.connection, serializer=JSONSerializer)

    @staticmethod
    def job_id(operation: dict) -> str:
        return f"{operation['operation_id']}-{operation['delivery']}"

    def status(self, operation: dict) -> str | None:
        try:
            return Job.fetch(self.job_id(operation), connection=self.connection,
                             serializer=JSONSerializer).get_status(refresh=True).value
        except NoSuchJobError:
            return None

    def enqueue(self, operation: dict) -> None:
        kind = operation["kind"]
        timeout = (self.config.document_index_timeout_seconds if kind == "index"
                   else self.config.document_delete_timeout_seconds)
        try:
            self.queue.enqueue(
                f"app.jobs.documents.{kind}_document", operation["operation_id"], operation["delivery"],
                job_id=self.job_id(operation), unique=True, job_timeout=timeout,
                retry=Retry(max=2, interval=[10, 30]), result_ttl=86400, failure_ttl=604800,
            )
        except DuplicateJobError:
            pass  # The previous enqueue may have succeeded before its reply was lost.

    def enqueue_cleanup(self, document: dict) -> None:
        identifier = uuid5(NAMESPACE_URL, f"{document['doc_id']}/{document['cleanup_after']}")
        try:
            self.queue.enqueue(
                "app.jobs.documents.cleanup_document", document["doc_id"], document["cleanup_after"],
                job_id=f"cleanup-{identifier}", unique=True,
                job_timeout=self.config.document_delete_timeout_seconds,
                retry=Retry(max=2, interval=[10, 30]), result_ttl=60, failure_ttl=60,
            )
        except DuplicateJobError:
            pass

    def close(self) -> None:
        self.connection.close()
