import logging
import time
from pathlib import Path

class AsyncFormatter(logging.Formatter):
    """Formatter optimized for async EC2 operations"""
    def format(self, record):
        # Basic instance info
        instance_id = getattr(record, 'instance_id', '')
        instance_name = getattr(record, 'instance_name', '')
        operation = getattr(record, 'operation', '')
        
        # Process and task info
        process_info = f"[p{record.process}"
        if hasattr(record, 'task_name'):
            process_info += f"|{record.task_name}]"
        else:
            process_info += "]"

        # Instance context
        if instance_id and instance_name:
            instance_info = f"[{instance_id}|{instance_name}"
            if operation:
                instance_info += f"|{operation}"
            instance_info += "]"
        else:
            instance_info = ""

        # Build the message
        msg = (
            f"[{self.formatTime(record)}] "
            f"{process_info} "
            f"{instance_info} "
            f"{record.levelname} - {record.getMessage()}"
        )

        # Add exception info if present
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"

        return msg.strip()

def setup_logger(log_file: str = "fmbench-orchestrator.log") -> logging.Logger:
    """Set up a simple logger with async operation support"""
    # Create logger
    logger = logging.getLogger("fmbench-orchestrator")
    logger.setLevel(logging.INFO)

    # Configure formatter with ISO timestamp
    formatter = AsyncFormatter(
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Create file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Initial log
    logger.info("Logger initialized", extra={
        'operation': 'init',
        'task_name': 'main'
    })

    return logger

# Create global logger instance
logger = setup_logger()
