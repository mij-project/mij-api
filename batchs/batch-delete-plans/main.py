from common.logger import Logger
from delete_plans_domain import DeletePlansDomain


def main():
    logger = Logger.get_logger()
    logger.info("START BATCH DELETE PLANS")
    domain = DeletePlansDomain(logger)
    domain._exec()
    logger.info("END BATCH DELETE PLANS")


if __name__ == "__main__":
    main()
