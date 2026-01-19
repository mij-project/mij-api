
from common.logger import Logger
from send_reservation_message import SendReservationMessage

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH SEND RESERVATION MESSAGE")
    send_reservation_message = SendReservationMessage(logger)
    send_reservation_message._exec()
    logger.info("END BATCH SEND RESERVATION MESSAGE")

if __name__ == "__main__":
    main()