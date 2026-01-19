import os
from app.services.s3.ecs_task import run_ecs_task
from app.core.logger import Logger

logger = Logger.get_logger()


def trigger_batch_generate_thumbnail_messageassets(message_assets_id: str):
    """
    メッセージアセットのサムネイルを生成する
    """
    try:
        ECS_SUBNETS = (
            os.environ.get("ECS_SUBNETS", "").split(",")
            if os.environ.get("ECS_SUBNETS")
            else []
        )
        ECS_SECURITY_GROUPS = (
            os.environ.get("ECS_SECURITY_GROUPS", "").split(",")
            if os.environ.get("ECS_SECURITY_GROUPS")
            else []
        )
        ECS_ASSIGN_PUBLIC_IP = os.environ.get("ECS_ASSIGN_PUBLIC_IP", "ENABLED")
        network_configuration = {
            "awsvpcConfiguration": {
                "subnets": ECS_SUBNETS,
                "securityGroups": ECS_SECURITY_GROUPS,
                "assignPublicIp": ECS_ASSIGN_PUBLIC_IP,
            }
        }
        run_ecs_task(
            cluster=os.environ.get("ECS_VIDEO_BATCH"),
            task_definition=os.environ.get(
                "ECS_GENERATE_THUMBNAIL_MESSAGE_ASSETS_TASK_DEFINITION"
            ),
            launch_type="FARGATE",
            overrides={
                "containerOverrides": [
                    {
                        "name": os.environ.get("ECS_VODEO_CONTAINER"),
                        "environment": [
                            {"name": "ENV", "value": os.environ.get("ENV")},
                            {
                                "name": "AWS_REGION",
                                "value": os.environ.get("AWS_REGION"),
                            },
                            {
                                "name": "AWS_ACCESS_KEY_ID",
                                "value": os.environ.get("AWS_ACCESS_KEY_ID"),
                            },
                            {
                                "name": "AWS_SECRET_ACCESS_KEY",
                                "value": os.environ.get("AWS_SECRET_ACCESS_KEY"),
                            },
                            {
                                "name": "AWS_DEFAULT_REGION",
                                "value": os.environ.get("AWS_DEFAULT_REGION"),
                            },
                            {
                                "name": "MESSAGE_ASSETS_ID",
                                "value": str(message_assets_id),
                            },
                            {
                                "name": "BUCKET",
                                "value": os.environ.get("MESSAGE_ASSETS_BUCKET_NAME"),
                            },
                            {
                                "name": "ENCRYPTION_KEY",
                                "value": os.environ.get("KMS_ALIAS_MESSAGE_ASSETS"),
                            }
                        ],
                    }
                ]
            },
            network_configuration=network_configuration,
        )
    except Exception as e:
        logger.exception(f"Failed to trigger batch generate thumbnail message assets: {e}")
        return
