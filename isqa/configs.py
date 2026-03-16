import os

from rich.console import Console

from isqa.common import GlobalFlags
from isqa.logger import get_logger

logger = get_logger()
console = Console()
settings = GlobalFlags()
gitlab_auth_object = None


def ensure_directory_exists(path: str):
    """
    Ensures a directory exists using the os module.
    Creates the directory if it doesn't exist.
    Handles creation of parent directories if they don't exist.
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            logger.info(f"Directory has been created: {path}")
    except OSError as e:
        logger.error(f"Error creating directory '{path}': {e}")
