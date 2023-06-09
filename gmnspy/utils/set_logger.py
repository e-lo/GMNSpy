"""
Establishes logging parameters.

Logger is run at import.
"""
import logging
from os.path import join
from tempfile import gettempdir


def build_logger():
    """Build logger object.

    Returns: Logger object.
    """
    logger = logging.getLogger("gmnspy")
    handler_name = "gmnspy"

    if len([h for h in logger.handlers if h.name and handler_name == h.name]) > 0:
        return logger

    log_path = join(gettempdir(), "gmnspy.log")
    FORMATTER = logging.Formatter("%(asctime)s;%(levelname)s ; %(message)s", datefmt="%H:%M:%S:")
    ch = logging.FileHandler(log_path)
    ch.setFormatter(FORMATTER)
    ch.set_name(handler_name)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

    return logger


logger = build_logger()
