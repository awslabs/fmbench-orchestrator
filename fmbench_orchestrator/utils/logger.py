import logging
from pathlib import Path


def setup_logger(log_file: str = "fmbench-orchestrator.log") -> logging.Logger:
    """
    Set up a centralized logger for the application.

    Args:
        log_file: Name of the log file

    Returns:
        logging.Logger: Configured logger instance
    """
    # Create logger
    logger = logging.getLogger("fmbench-orchestrator")
    logger.setLevel(logging.INFO)

    # Create formatters
    formatter = logging.Formatter(
        "[%(asctime)s] p%(process)s {%(filename)s:%(lineno)d} %(levelname)s - %(message)s"
    )

    # Create handlers
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Create a global logger instance
logger = setup_logger()
