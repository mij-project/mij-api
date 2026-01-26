from common.logger import Logger
from creators_categories_reco import CreatorsCategoriesRecommend

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH CREATORS CATEGORIES RECOMMEND")
    creators_categories_reco = CreatorsCategoriesRecommend(logger)
    creators_categories_reco.exec()
    logger.info("END BATCH CREATORS CATEGORIES RECOMMEND")

if __name__ == "__main__":
    main()