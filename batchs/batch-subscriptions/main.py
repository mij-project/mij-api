from common.logger import Logger
from subscriptions import SubscriptionsDomain

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH SUBSCRIPTIONS")
    subscriptions = SubscriptionsDomain(logger)
    subscriptions._exec()
    logger.info("END BATCH SUBSCRIPTIONS")

if __name__ == "__main__":
    main()