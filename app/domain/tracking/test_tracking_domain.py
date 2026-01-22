import pytest
from unittest.mock import MagicMock
from app.domain.tracking.tracking_domain import TrackingDomain
from app.schemas.tracking import PostPurchaseTrackingPayload, PostViewTrackingPayload, ProfileViewTrackingPayload
from app.models.user import Users

@pytest.fixture
def db_mock():
    db = MagicMock(name="SessionMock")
    return db

def test_track_profile_view_with_user(db_mock):
    payload = ProfileViewTrackingPayload(profile_user_id="123")
    user = Users(id="123")
    tracking_domain = TrackingDomain(db=db_mock)
    tracking_domain.track_profile_view(payload, user)
    assert True

def test_track_profile_view_without_user(db_mock):
    payload = ProfileViewTrackingPayload(profile_user_id="123")
    tracking_domain = TrackingDomain(db=db_mock)
    tracking_domain.track_profile_view(payload)
    assert True

def test_track_post_view(db_mock):
    payload = PostViewTrackingPayload(post_id="123", user_id="123", watched_duration_sec=10, video_duration_sec=100)
    tracking_domain = TrackingDomain(db=db_mock)
    tracking_domain.track_post_view(payload)
    assert True

def test_track_post_view_without_user(db_mock):
    payload = PostViewTrackingPayload(post_id="123", user_id=None, watched_duration_sec=10, video_duration_sec=100)
    tracking_domain = TrackingDomain(db=db_mock)
    tracking_domain.track_post_view(payload)
    assert True

def test_track_post_view_without_user_and_watched_duration_sec(db_mock):
    payload = PostViewTrackingPayload(post_id="123", user_id=None, watched_duration_sec=None, video_duration_sec=None)
    tracking_domain = TrackingDomain(db=db_mock)
    tracking_domain.track_post_view(payload)
    assert True

def test_track_post_purchase(db_mock):
    payload = PostPurchaseTrackingPayload(post_id="123", user_id="123")
    tracking_domain = TrackingDomain(db=db_mock)
    tracking_domain.track_post_purchase(payload)
    assert True

def test_track_post_purchase_without_user(db_mock):
    with pytest.raises(Exception):
        payload = PostPurchaseTrackingPayload(post_id="123", user_id=None)
        tracking_domain = TrackingDomain(db=db_mock)
        tracking_domain.track_post_purchase(payload)