from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import os
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.models.social import Follows, Likes, Comments, Bookmarks
from app.crud import followes_crud, likes_crud, comments_crud, bookmarks_crud
from app.schemas.social import (
    CommentCreate, CommentResponse, CommentUpdate,
    FollowResponse, LikeResponse, BookmarkResponse,
    UserBasicResponse
)

BASE_URL = os.getenv("CDN_BASE_URL")

router = APIRouter()

# フォロー関連エンドポイント
@router.post("/follow/{user_id}", response_model=dict)
def toggle_follow(
    user_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """フォロー/フォロー解除のトグル"""
    return followes_crud.toggle_follow(db, current_user.id, user_id)

@router.get("/follow/status/{user_id}", response_model=dict)
def get_follow_status(
    user_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """フォロー状態を確認"""
    is_following = followes_crud.is_following(db, current_user.id, user_id)
    return {"following": is_following}

@router.get("/followers/{user_id}", response_model=List[UserBasicResponse])
def get_followers(
    user_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """フォロワー一覧を取得"""
    followers = followes_crud.get_followers(db, user_id, skip, limit)
    return [
        UserBasicResponse(
            id=follower_id,
            username=username,
            profile_name=profile_name,
            avatar_storage_key=f"{BASE_URL}/{avatar_url}" if avatar_url else None
        ) for follower_id, profile_name, username, avatar_url in followers
    ]

@router.get("/following/{user_id}", response_model=List[UserBasicResponse])
def get_following(
    user_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """フォロー中ユーザー一覧を取得"""
    following = followes_crud.get_following(db, user_id, skip, limit)
    return [
        UserBasicResponse(
            id=following_id,
            username=username,
            profile_name=profile_name,
            avatar_storage_key=f"{BASE_URL}/{avatar_url}" if avatar_url else None
        ) for following_id, profile_name, username, avatar_url in following
    ]

# いいね関連エンドポイント
@router.post("/like/{post_id}", response_model=dict)
def toggle_like(
    post_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """いいね/いいね取り消しのトグル"""
    return likes_crud.toggle_like(db, current_user.id, post_id)

@router.get("/like/status/{post_id}", response_model=dict)
def get_like_status(
    post_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """いいね状態を確認"""
    is_liked = likes_crud.is_liked(db, current_user.id, post_id)
    likes_count = likes_crud.get_likes_count(db, post_id)
    return {"liked": is_liked, "likes_count": likes_count}

@router.post("/like/status/bulk", response_model=dict)
def get_likes_status_bulk(
    post_ids: List[UUID],
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """複数投稿のいいね状態を一括取得"""
    result = {}
    for post_id in post_ids:
        is_liked = likes_crud.is_liked(db, current_user.id, post_id)
        likes_count = likes_crud.get_likes_count(db, post_id)
        result[str(post_id)] = {
            "liked": is_liked,
            "likes_count": likes_count
        }
    return result

@router.get("/liked-posts", response_model=List[dict])
def get_liked_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """いいねした投稿一覧を取得"""
    posts = likes_crud.get_liked_posts_by_user_id(db, current_user.id, skip, limit)
    return [
        {
            "id": post.id,
            "title": post.title,
            "description": post.description,
            "created_at": post.created_at,
            "creator_user_id": post.creator_user_id
        } for post in posts
    ]

# コメント関連エンドポイント
@router.post("/comments/{post_id}", response_model=CommentResponse)
def create_comment(
    post_id: UUID,
    comment: CommentCreate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """コメントを作成"""
    new_comment = comments_crud.create_comment(
        db, post_id, current_user.id, comment.body, comment.parent_comment_id
    )
    return CommentResponse(
        id=new_comment.id,
        post_id=new_comment.post_id,
        user_id=new_comment.user_id,
        parent_comment_id=new_comment.parent_comment_id,
        body=new_comment.body,
        created_at=new_comment.created_at,
        updated_at=new_comment.updated_at,
        user_username=current_user.username,
        user_avatar=current_user.avatar_storage_key
    )

@router.get("/comments/{post_id}", response_model=List[CommentResponse])
def get_comments(
    post_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """投稿のコメント一覧を取得"""
    comments = comments_crud.get_comments_by_post_id(db, post_id, skip, limit)
    result = []
    for comment in comments:
        result.append(CommentResponse(
            id=comment.id,
            post_id=comment.post_id,
            user_id=comment.user_id,
            parent_comment_id=comment.parent_comment_id,
            body=comment.body,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            user_username=comment.user.username,
            user_avatar=comment.user.avatar_storage_key
        ))
    return result

@router.get("/comments/{parent_comment_id}/replies", response_model=List[CommentResponse])
def get_comment_replies(
    parent_comment_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """返信コメント一覧を取得"""
    replies = comments_crud.get_replies_by_parent_id(db, parent_comment_id, skip, limit)
    result = []
    for reply in replies:
        result.append(CommentResponse(
            id=reply.id,
            post_id=reply.post_id,
            user_id=reply.user_id,
            parent_comment_id=reply.parent_comment_id,
            body=reply.body,
            created_at=reply.created_at,
            updated_at=reply.updated_at,
            user_username=reply.user.username,
            user_avatar=reply.user.avatar_storage_key
        ))
    return result

@router.put("/comments/{comment_id}", response_model=CommentResponse)
def update_comment(
    comment_id: UUID,
    comment_update: CommentUpdate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """コメントを更新"""
    updated_comment = comments_crud.update_comment(
        db, comment_id, comment_update.body, current_user.id
    )
    if not updated_comment:
        raise HTTPException(status_code=404, detail="コメントが見つからないか、編集権限がありません")
    
    return CommentResponse(
        id=updated_comment.id,
        post_id=updated_comment.post_id,
        user_id=updated_comment.user_id,
        parent_comment_id=updated_comment.parent_comment_id,
        body=updated_comment.body,
        created_at=updated_comment.created_at,
        updated_at=updated_comment.updated_at,
        user_username=current_user.username,
        user_avatar=current_user.avatar_storage_key
    )

@router.delete("/comments/{comment_id}", response_model=dict)
def delete_comment(
    comment_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """コメントを削除"""
    success = comments_crud.delete_comment(db, comment_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="コメントが見つからないか、削除権限がありません")
    
    return {"message": "コメントを削除しました"}

# ブックマーク関連エンドポイント
@router.post("/bookmark/{post_id}", response_model=dict)
def toggle_bookmark(
    post_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """ブックマーク/ブックマーク削除のトグル"""
    return bookmarks_crud.toggle_bookmark(db, current_user.id, post_id)

@router.get("/bookmark/status/{post_id}", response_model=dict)
def get_bookmark_status(
    post_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """ブックマーク状態を確認"""
    is_bookmarked = bookmarks_crud.is_bookmarked(db, current_user.id, post_id)
    return {"bookmarked": is_bookmarked}

@router.post("/bookmark/status/bulk", response_model=dict)
def get_bookmarks_status_bulk(
    post_ids: List[UUID],
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """複数投稿のブックマーク状態を一括取得"""
    result = {}
    for post_id in post_ids:
        is_bookmarked = bookmarks_crud.is_bookmarked(db, current_user.id, post_id)
        result[str(post_id)] = {
            "bookmarked": is_bookmarked
        }
    return result

@router.get("/bookmarks", response_model=List[dict])
def get_bookmarks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """ブックマークした投稿一覧を取得"""
    posts = bookmarks_crud.get_bookmarks_by_user_id(db, current_user.id, skip, limit)
    return [
        {
            "id": post.id,
            "title": post.title,
            "description": post.description,
            "created_at": post.created_at,
            "creator_user_id": post.creator_user_id
        } for post in posts
    ]