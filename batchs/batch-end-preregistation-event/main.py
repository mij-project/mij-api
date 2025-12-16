from common.logger import Logger
from end_preregistation_event import EndPreregistationEvent

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH END PREREGISTATION EVENT")
    end_preregistation_event = EndPreregistationEvent()
    end_preregistation_event.exec()
    logger.info("END BATCH END PREREGISTATION EVENT")

if __name__ == "__main__":
    main()