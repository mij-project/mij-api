import sys
import logging

class Logger():
    logger = None

    def __init__(self):
        if Logger.logger is None:
            Logger.logger = logging.getLogger(__name__)
            Logger.logger.setLevel(logging.INFO)
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s "
                "- %(pathname)s:%(lineno)d - %(message)s"
            )
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            Logger.logger.addHandler(console_handler)
    
    @staticmethod
    def get_logger():
        if Logger.logger is None:
            Logger()
        return Logger.logger