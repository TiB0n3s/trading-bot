import logging
from pathlib import Path

from services.container import ApplicationContainer
from services.fill_stream_service import FillStreamService

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(ROOT / "fill_stream.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def main() -> None:
    container = ApplicationContainer.create_default(
        logger=logger,
        signal_executor_factory=lambda: None,
    )
    FillStreamService.from_container(container).run()


if __name__ == "__main__":
    main()
