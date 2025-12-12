# app/services/s3/media_covert.py
from app.services.s3.client import s3_client_for_mc
from app.services.s3.client import (
    MEDIA_BUCKET_NAME, 
    INGEST_BUCKET, 
    MEDIACONVERT_ROLE_ARN,
    OUTPUT_COVERT_KMS_ARN
)


def build_media_rendition_job_settings(input_key: str, output_prefix: str, usermeta: dict):
    """
    メディアレンディションジョブ作成

    Args:
        input_key (str): 入力キー
        output_key (str): 出力キー
        usermeta (dict): ユーザーメタデータ

    Returns:
        dict: ジョブ設定
    """
    input_s3 = f"s3://{INGEST_BUCKET}/{input_key}"

    # 出力ディレクトリ（末尾に / が必要）
    out_dir = f"s3://{MEDIA_BUCKET_NAME}/{output_prefix.rsplit('/', 1)[0]}/"

    
    return {
        "Role": MEDIACONVERT_ROLE_ARN,
        "Settings": {
            "TimecodeConfig": {"Source": "ZEROBASED"},
            "Inputs": [{
                "FileInput": input_s3,
                "AudioSelectors": {"Audio Selector 1": {"DefaultSelection": "DEFAULT"}},
                "VideoSelector": {"ColorSpace": "FOLLOW"},
            }],
            "OutputGroups": [{
                "Name": "File Group",
                "OutputGroupSettings": {
                    "Type": "FILE_GROUP_SETTINGS",
                    "FileGroupSettings": {
                        "Destination": out_dir,
                        "DestinationSettings": {
                            "S3Settings": {
                                "Encryption": {
                                    "EncryptionType": "SERVER_SIDE_ENCRYPTION_KMS",
                                    "KmsKeyArn": OUTPUT_COVERT_KMS_ARN  # ← 環境から渡す or settingsで解決
                                }
                            }
                        }
                    }
                },
                "Outputs": [{
                    "ContainerSettings": {"Container": "MP4"},
                    "VideoDescription": {
                        "Height": 480,
                        "RespondToAfd": "NONE",
                        "ScalingBehavior": "DEFAULT",
                        "CodecSettings": {"Codec": "H_264","H264Settings": {
                            "RateControlMode": "QVBR",
                            "QvbrSettings": {"QvbrQualityLevel": 7},
                            "GopSize": 90, "GopSizeUnits": "FRAMES",
                            "MaxBitrate": 1_200_000
                        }},
                    },
                    "AudioDescriptions": [{
                        "CodecSettings": {"Codec": "AAC","AacSettings": {
                            "Bitrate": 96_000, "CodingMode": "CODING_MODE_2_0", "SampleRate": 48_000
                        }}
                    }],
                }],
            }],
        },
        "StatusUpdateInterval": "SECONDS_30",
        "Priority": 0,
        "UserMetadata": usermeta,
        "Tags": {"type": "rendition", "app": "mij"},
    }

def build_preview_mp4_settings(input_key: str, output_key: str, usermeta: dict):
    """
    プレビューMP4ジョブ作成

    Args:
        input_key (str): 入力キー
        output_key (str): 出力キー
        usermeta (dict): ユーザーメタデータ

    Returns:
        dict: ジョブ設定
    """
    input_s3  = f"s3://{INGEST_BUCKET}/{input_key}"
    out_dir   = f"s3://{MEDIA_BUCKET_NAME}/{output_key.rsplit('/',1)[0]}/"
    out_name  = output_key.split("/")[-1]
    return {
        "Role": MEDIACONVERT_ROLE_ARN,
        "Settings": {
            "TimecodeConfig": {"Source": "ZEROBASED"},
            "Inputs": [{
                "FileInput": input_s3,
                "AudioSelectors": {"Audio Selector 1": {"DefaultSelection": "DEFAULT"}},
                "VideoSelector": {"ColorSpace": "FOLLOW"},
            }],
            "OutputGroups": [{
                "Name": "File Group",
                "OutputGroupSettings": {
                    "Type": "FILE_GROUP_SETTINGS",
                    "FileGroupSettings": {
                        "Destination": out_dir,
                        "DestinationSettings": {
                            "S3Settings": {
                                "Encryption": {
                                    "EncryptionType": "SERVER_SIDE_ENCRYPTION_KMS",
                                    "KmsKeyArn": OUTPUT_COVERT_KMS_ARN
                                }
                            }
                        }
                    }
                },
                "Outputs": [{
                    "ContainerSettings": {"Container": "MP4"},
                    "VideoDescription": {
                        "Height": 480,
                        "RespondToAfd": "NONE",
                        "ScalingBehavior": "DEFAULT",
                        "CodecSettings": {"Codec": "H_264","H264Settings": {
                            "RateControlMode": "QVBR",
                            "QvbrSettings": {"QvbrQualityLevel": 7},
                            "GopSize": 90, "GopSizeUnits": "FRAMES",
                            "MaxBitrate": 1_200_000
                        }},
                    },
                    "AudioDescriptions": [{
                        "CodecSettings": {"Codec": "AAC","AacSettings": {
                            "Bitrate": 96_000, "CodingMode": "CODING_MODE_2_0", "SampleRate": 48_000
                        }}
                    }],
                    "OutputName": out_name,
                }],
            }],
        },
        "StatusUpdateInterval": "SECONDS_30",
        "Priority": 0,
        "UserMetadata": usermeta,
        "Tags": {"type": "preview", "app": "mij"},
    }

def build_hls_abr2_settings(input_key: str, output_prefix: str, usermeta: dict):
    """
    HLS ABR4ジョブ作成
    """
    input_s3 = f"s3://{INGEST_BUCKET}/{input_key}"
    dest     = f"s3://{MEDIA_BUCKET_NAME}/{output_prefix.strip('/')}/"

    file_prefix = usermeta.get("renditionJobId")

    def profile_for(h: int) -> str:
        return "HIGH" if h >= 1080 else "MAIN"

    def stream(h, w, max_br, a_br, name_suffix):
        return {
            "VideoDescription": {
                "Height": h,
                "RespondToAfd": "NONE",
                "ScalingBehavior": "DEFAULT",
                "CodecSettings": {
                    "Codec": "H_264",
                    "H264Settings": {
                        "RateControlMode": "QVBR",
                        "MaxBitrate": max_br,
                        "QvbrSettings": {"QvbrQualityLevel": 8},
                        "GopSizeUnits": "SECONDS",
                        "GopSize": 3.0,
                        "NumberBFramesBetweenReferenceFrames": 2,
                        "AdaptiveQuantization": "HIGH",
                        "SceneChangeDetect": "TRANSITION_DETECTION",
                        "SlowPal": "DISABLED",
                        "FramerateControl": "INITIALIZE_FROM_SOURCE",
                        "ParControl": "INITIALIZE_FROM_SOURCE",
                        "Syntax": "DEFAULT",
                        "CodecLevel": "AUTO",
                        "CodecProfile": profile_for(h),
                    }
                }
            },
            "AudioDescriptions": [{
                "AudioSourceName": "Audio Selector 1",
                "CodecSettings": {
                    "Codec": "AAC",
                    "AacSettings": {"Bitrate": a_br, "CodingMode": "CODING_MODE_2_0", "SampleRate": 48000}
                },
            }],
            "ContainerSettings": {"Container": "M3U8"},
            "NameModifier": name_suffix,           # 例: "_360p"
            "OutputSettings": {
                "HlsSettings": {
                    "SegmentModifier": f"{file_prefix}_"
                }
            }
        }

    return {
        "Role": MEDIACONVERT_ROLE_ARN,
        "Settings": {
            "TimecodeConfig": {"Source": "ZEROBASED"},
            "Inputs": [{
                "FileInput": input_s3,
                "AudioSelectors": {"Audio Selector 1": {"DefaultSelection": "DEFAULT"}},
                "VideoSelector": {"ColorSpace": "FOLLOW"},
            }],
            "OutputGroups": [{
                "Name": "HLS",
                "OutputGroupSettings": {
                    "Type": "HLS_GROUP_SETTINGS",
                    "HlsGroupSettings": {
                        "Destination": dest,
                        "SegmentLength": 6,
                        "MinSegmentLength": 0,
                        "MinFinalSegmentLength": 0,
                        "DirectoryStructure": "SINGLE_DIRECTORY",
                        "ManifestDurationFormat": "INTEGER",
                        "OutputSelection": "MANIFESTS_AND_SEGMENTS",
                        "SegmentControl": "SEGMENTED_FILES",
                        "CodecSpecification": "RFC_6381",
                        "DestinationSettings": {
                            "S3Settings": {
                                "Encryption": {
                                    "EncryptionType": "SERVER_SIDE_ENCRYPTION_KMS",
                                    "KmsKeyArn": OUTPUT_COVERT_KMS_ARN
                                }
                            }
                        }
                    }
                },
                "Outputs": [
                    stream(480,   854, 1_200_000,   96_000, "_540p"),
                    stream(1080, 1920, 4_500_000,  128_000, "_1080p"),
                ]
            }]
        },
        "StatusUpdateInterval": "SECONDS_30",
        "Priority": 0,
        "UserMetadata": usermeta,
        "Tags": {"type": "final-hls", "app": "mij"},
    }