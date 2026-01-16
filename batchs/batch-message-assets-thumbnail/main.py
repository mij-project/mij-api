from common.logger import Logger
from generate_message_assets_thumbnail import GenerateMessageAssetsThumbnail

def main():
    logger = Logger.get_logger()
    generate_message_assets_thumbnail = GenerateMessageAssetsThumbnail(logger)
    generate_message_assets_thumbnail.exec()

if __name__ == "__main__":
    main()