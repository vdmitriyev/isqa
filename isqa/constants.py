"""Provides module specific constants."""

import os
from pathlib import Path

# BASEDIR = os.path.abspath(os.path.dirname(__file__))
BASEDIR = os.path.join(Path(__file__).resolve().parent.parent)
LOGGER_NAME = "isqa"
LOG_FILE_NAME = "isqa.log"
APP_LOG_LEVEL = os.environ.get("APP_LOG_LEVEL", "INFO").upper()
EMAIL_TEMPLATES_DIR = "templates"
DEFAULT_ENV_EXTRA_CONFIG = "extra.env"
ISSUES_REORDER_ATTEMPT_SLEEP_SECONDS = 10

LOG_FILE_PATH = os.path.join(BASEDIR, LOG_FILE_NAME)
JSON_FILE_DUMPS_PATH = os.path.join(BASEDIR, ".jsons")
EMAIL_TEMPLATES_PATH = os.path.join(BASEDIR, EMAIL_TEMPLATES_DIR)
