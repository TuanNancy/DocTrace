"""python -m app.worker: standard RQ fetch/fork/execute worker with retry scheduler."""
import logging

from redis import Redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from app.core.config import get_config


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    # RQ sets its own blocking socket timeout. Do not reuse the producer's short timeout.
    connection = Redis.from_url(config.redis_url, socket_connect_timeout=5)
    try:
        queue = Queue(config.rq_queue_name, connection=connection, serializer=JSONSerializer)
        worker = Worker([queue], connection=connection, serializer=JSONSerializer, maintenance_interval=30)
        worker.work(with_scheduler=True)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
