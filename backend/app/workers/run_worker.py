"""Stand-alone worker process:  ``python -m app.workers.run_worker``

Use this in production (set ``EMBEDDED_WORKER=false`` on the API service) so that long crawls do not
share a process with web requests. It needs the same ``DATABASE_URL`` as the API."""
import asyncio
import signal

from app.database import init_db
from app.logging_config import setup_logging
from app.workers.runner import JobRunner


async def main() -> None:
    setup_logging()
    init_db()
    runner = JobRunner()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.stop)
        except NotImplementedError:  # Windows event loops do not support add_signal_handler
            pass
    await runner.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
