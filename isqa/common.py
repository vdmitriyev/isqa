import json
import os
from datetime import datetime

from isqa.logger import get_logger

logger = get_logger()


class GlobalFlags:
    """Class to hold global configuration state."""

    dry_run: bool = False
    verbose: bool = False


def __save_json__(content: dict, filepath: str = None):
    """
    Saves the provided dictionary to a JSON file.

    If no filename is provided, a unique filename based on the current timestamp will be generated.

    Args:
        content (dict): The dictionary content to be saved as JSON.
        filepath (str, optional): The desired name for the JSON file (e.g., "data.json").
                                    If None, a timestamped filename is used. Defaults to None.
    """
    from isqa.configs import ensure_directory_exists
    from isqa.constants import JSON_FILE_DUMPS_PATH

    ensure_directory_exists(JSON_FILE_DUMPS_PATH)

    if not filepath:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(JSON_FILE_DUMPS_PATH, f"dump_{timestamp}.json")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=4)  # Pretty print JSON with indent=4
        logger.debug(f"API response successfully saved to: '{filepath}'")
        return filepath
    except IOError as e:
        logger.error(
            f"I/O Error: Could not save response to: '{filepath}'. Details: {e}"
        )
    except Exception as e:
        logger.error(
            f"An unexpected error occurred while saving response to: '{filepath}'. Exception: {e}",
            exc_info=True,
        )
