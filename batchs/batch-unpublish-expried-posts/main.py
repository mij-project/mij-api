from common.logger import Logger
from batch_unpublish_expried_posts import BatchUnpublishExpriedPosts

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH UNPUBLISH EXPIRED POSTS")
    batch_unpublish_expried_posts = BatchUnpublishExpriedPosts(logger)
    batch_unpublish_expried_posts._exec()
    logger.info("END BATCH UNPUBLISH EXPIRED POSTS")

if __name__ == "__main__":
    main()