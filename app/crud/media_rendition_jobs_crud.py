from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.media_rendition_jobs import MediaRenditionJobs

def create_media_rendition_job(db: Session, media_rendition_job_data: dict) -> MediaRenditionJobs:
    """
    メディアレンディションジョブ作成
    """
    db_media_rendition_job = MediaRenditionJobs(**media_rendition_job_data)
    db.add(db_media_rendition_job)
    db.flush()
    return db_media_rendition_job

def update_media_rendition_job(db: Session, media_rendition_job_id: str, media_rendition_job_data: dict) -> MediaRenditionJobs:
    """
    メディアレンディションジョブ更新
    """
    db_media_rendition_job = db.query(MediaRenditionJobs).filter(MediaRenditionJobs.id == media_rendition_job_id).first()
    if not db_media_rendition_job:
        return None
    
    # オブジェクトの属性を直接更新
    for key, value in media_rendition_job_data.items():
        if hasattr(db_media_rendition_job, key):
            setattr(db_media_rendition_job, key, value)
    
    db.add(db_media_rendition_job)
    db.flush()
    return db_media_rendition_job
    
def get_media_rendition_job_by_id(db: Session, media_rendition_job_id: str) -> MediaRenditionJobs:
    """
    メディアレンディションジョブ取得
    """
    return db.query(MediaRenditionJobs).filter(MediaRenditionJobs.id == media_rendition_job_id).first()

def delete_media_rendition_job(db: Session, asset_id: str) -> bool:
    """
    メディアレンディションジョブ削除
    """
    db.query(MediaRenditionJobs).filter(MediaRenditionJobs.asset_id == asset_id).delete()
    db.commit()
    return True