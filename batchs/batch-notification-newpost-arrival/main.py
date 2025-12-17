from common.logger import Logger
from newpost_arrival_domain import NewPostArrivalDomain

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH NEW POST ARRIVAL")
    domain = NewPostArrivalDomain(logger)
    domain._exec()
    logger.info("END BATCH NEW POST ARRIVAL")

if __name__ == "__main__":
    main()