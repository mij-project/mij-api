from batch_main_sample_video import BatchMainSampleVideo
from common.logger import Logger

def main():
    logger = Logger.get_logger()
    logger.info("START BATCH MAIN SAMPLE VIDEO")
    batch_main_sample_video = BatchMainSampleVideo(logger)
    batch_main_sample_video._exec()
    logger.info("END BATCH MAIN SAMPLE VIDEO")

if __name__ == "__main__":
    main()