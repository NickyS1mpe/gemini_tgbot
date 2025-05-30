import logging
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)
log_file = ""


def load_log_file(log_path):
    global log_file
    log_file = log_path


def setup_logger(log_path):
    load_log_file(log_path)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1 * 1024 * 1024,  # 1 MB
        backupCount=2
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))

    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger.info("Logger setup successfully.")


def log_message(user_name, chat_name, is_bot, message_type, message_content):
    """Logs message details for tracking bot interactions."""
    logger.info(
        ' %(user_name)s - %(chat_name)s - %(is_bot)s - %(message_type)s - %(message_content)s',
        {'user_name': user_name,
         'chat_name': chat_name, 'is_bot': is_bot,
         'message_type': message_type,
         'message_content': message_content})
