import logging
import os


def configure_logging(log_path=None):
    logger = logging.getLogger("mesh_convert")
    logger.setLevel(logging.INFO)
    logger.handlers[:] = []

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stream_handler)

    if log_path:
        parent = os.path.dirname(os.path.abspath(log_path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)

    return logger
