from common.logger import Logger
from AdminNotification import AdminNotification

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH ADMIN NOTIFICATION")
    admin_notification = AdminNotification(logger)
    admin_notification._exec()
    logger.info("END BATCH ADMIN NOTIFICATION")

if __name__ == "__main__":
    main()