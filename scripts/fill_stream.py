import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from services.container import ApplicationContainer
from services.fill_stream_service import FillStreamService

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
