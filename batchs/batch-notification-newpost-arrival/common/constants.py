import os

ENV = os.environ.get("ENV", "stg")
POSTGRES_USER=os.environ.get("POSTGRES_USER", "user")
POSTGRES_PASSWORD=os.environ.get("POSTGRES_PASSWORD", "password")
POSTGRES_DB=os.environ.get("POSTGRES_DB", "mij_db")
POSTGRES_SERVER=os.environ.get("POSTGRES_SERVER", "localhost")
POSTGRES_PORT=os.environ.get("POSTGRES_PORT", "5432")

DATABASE_URL=f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_SERVER}:{POSTGRES_PORT}/{POSTGRES_DB}"

EMAIL_BACKEND="auto"
EMAIL_ENABLED="true"
MAIL_FROM="no-reply@mijfans.jp"
MAIL_FROM_NAME="mijfans"
AWS_REGION="ap-northeast-1"
SES_CONFIGURATION_SET=os.environ.get("SES_CONFIGURATION_SET", "stg-outbound") 