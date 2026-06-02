import logging

from services.container import ApplicationContainer
from services.fill_poller_service import FillPollerService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def poll_fills():
    container = ApplicationContainer.create_default(
        logger=logger,
        signal_executor_factory=lambda: None,
    )
    return FillPollerService.from_container(container).poll_fills()


if __name__ == "__main__":
    result = poll_fills()
    print(f"rows_written: {result.updated}")
