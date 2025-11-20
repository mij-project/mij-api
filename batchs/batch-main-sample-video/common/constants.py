import os

TEMP_VIDEO_BUCKET = os.environ.get("TEMP_VIDEO_BUCKET", "mij-ingest-dev")
TEMP_VIDEO_DESTINATION = os.environ.get("TEMP_VIDEO_DESTINATION", "post-media/276081e3-6647-48b2-a257-170c9c4a6b0e/main/12a85465-4a4f-49b5-971a-94012b2ca1fc/5d1df064-65f3-41bc-bb00-87498daaa398.mp4")
SAMPLE_VIDEO_BUCKET = os.environ.get("SAMPLE_VIDEO_BUCKET", "mij-ingest-dev")
SAMPLE_VIDEO_DESTINATION = os.environ.get("SAMPLE_VIDEO_DESTINATION", "post-media/276081e3-6647-48b2-a257-170c9c4a6b0e/main/12a85465-4a4f-49b5-971a-94012b2ca1fc/sample_video.mp4")
MAIN_VIDEO_BUCKET = os.environ.get("MAIN_VIDEO_BUCKET", "mij-ingest-dev")
MAIN_VIDEO_DESTINATION = os.environ.get("MAIN_VIDEO_DESTINATION", "post-media/276081e3-6647-48b2-a257-170c9c4a6b0e/main/12a85465-4a4f-49b5-971a-94012b2ca1fc/main_video.mp4")
START_TIME = float(os.environ.get("START_TIME", "0.0"))
END_TIME = float(os.environ.get("END_TIME", "10.0"))
NEED_TRIM = bool(int(os.environ.get("NEED_TRIM", "0"))) # 0: false, 1: true

AWS_REGION = os.environ.get("AWS_REGION", "")
AWS_ACCESS = os.environ.get("AWS_ACCESS", "")
AWS_SECRET = os.environ.get("AWS_SECRET", "")
KMS_ARN = os.environ.get("KMS_ARN", "")