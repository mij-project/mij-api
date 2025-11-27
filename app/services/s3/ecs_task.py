import boto3
from typing import Optional
from app.core.logger import Logger
logger = Logger.get_logger()
from app.services.s3.client import ecs_client


def run_ecs_task(
    cluster: str,
    task_definition: str,
    launch_type: str,
    overrides: dict,
    network_configuration: Optional[dict] = None,
    count: int = 1,
    platform_version: str = "LATEST"
) -> dict:
    """
    ECSタスクを実行

    Args:
        cluster: ECSクラスター名またはARN
        task_definition: タスク定義（family:revision形式またはARN）
        launch_type: 起動タイプ（FARGATE, EC2, EXTERNAL）
        overrides: コンテナオーバーライド設定
        network_configuration: ネットワーク設定（Fargateでは必須）
        count: 起動するタスク数（デフォルト: 1）
        platform_version: Fargateプラットフォームバージョン（デフォルト: LATEST）

    Returns:
        dict: run_taskのレスポンス
    """
    try:
        client = ecs_client()

        params = {
            "cluster": cluster,
            "taskDefinition": task_definition,
            "launchType": launch_type,
            "overrides": overrides,
            "count": count,
        }

        # Fargateの場合はplatformVersionを追加
        if launch_type == "FARGATE":
            params["platformVersion"] = platform_version

            # networkConfigurationが必須
            if network_configuration:
                params["networkConfiguration"] = network_configuration
            else:
                logger.warning("Fargate launch type requires networkConfiguration")

        return client.run_task(**params)
    except Exception as e:
        logger.error(f"Failed to run ECS task: {e}")
        raise