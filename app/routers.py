from fastapi import APIRouter


# Customer routes
from app.api.endpoints.customer import (
    identity, media_assets, videos, users, auth,
    creater, gender, plans, categories, post,
    transcode_mc, top, category, ranking, social,
    preregistrations, account, auth_email_verify,
    conversations, order, sms_verifications, banners, video_temp, notifications as customer_notifications,
    search, creator_type, password_reset, user_settings, generation_media, subscriptions, user_provider
)

# Admin routes
from app.api.endpoints.admin import (
    admin, admin_auth, conversations as admin_conversations,
    preregistrations as admin_preregistrations,
    identity as admin_identity,
    profile_images as admin_profile_images,
    banners as admin_banners,
    post as admin_post,
    events as admin_events,
    company as admin_company,
    notifications as admin_notifications
)

# Debug routes
from app.api.endpoints.debug import debug_email


# Hook routes
from app.api.endpoints.hook.media_convert import router as media_convert_hook
from app.api.endpoints.hook.conversations import router as conversations_hook
from app.api.endpoints.hook.payment import router as payment_hook

# Payment routes
from app.api.endpoints.payments import credix

api_router = APIRouter()

# Hook routes
api_router.include_router(media_convert_hook, prefix="/webhooks", tags=["Webhooks"])
api_router.include_router(conversations_hook, prefix="/ws", tags=["WebSocket Conversations"])
api_router.include_router(payment_hook, prefix="/webhook", tags=["Payment"])



api_router.include_router(videos.router, prefix="/videos", tags=["Videos"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(password_reset.router, prefix="/auth/password-reset", tags=["Password Reset"])
api_router.include_router(creater.router, prefix="/creators", tags=["Creators"])
api_router.include_router(identity.router, prefix="/identity", tags=["Identity"])
api_router.include_router(gender.router, prefix="/gender", tags=["Gender"])
api_router.include_router(account.router, prefix="/account", tags=["Account"])
api_router.include_router(media_assets.router, prefix="/media-assets", tags=["Media Assets"])
api_router.include_router(plans.router, prefix="/plans", tags=["Plans"])
api_router.include_router(categories.router, prefix="/categories", tags=["Categories"])
api_router.include_router(post.router, prefix="/post", tags=["Post"])
api_router.include_router(top.router, prefix="/top", tags=["Top"])
api_router.include_router(transcode_mc.router, prefix="/transcodes", tags=["Transcode MC"])
api_router.include_router(category.router, prefix="/category", tags=["Category"])
api_router.include_router(ranking.router, prefix="/ranking", tags=["Ranking"])
api_router.include_router(social.router, prefix="/social", tags=["Social"])
api_router.include_router(preregistrations.router, prefix="/preregistrations", tags=["Preregistrations"])
api_router.include_router(auth_email_verify.router, prefix="/auth/email", tags=["Auth Email"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversations"])
api_router.include_router(order.router, prefix="/orders", tags=["Orders"])
api_router.include_router(sms_verifications.router, prefix="/sms-verifications", tags=["SMS Verifications"])
api_router.include_router(banners.router, prefix="/banners", tags=["Banners"])
api_router.include_router(video_temp.router, prefix="", tags=["Video Temp"])
api_router.include_router(customer_notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(search.router, prefix="", tags=["Search"])
api_router.include_router(creator_type.router, prefix="/creator-type", tags=["Creator Type"])
api_router.include_router(user_settings.router, prefix="/user-settings", tags=["User Settings"])
api_router.include_router(generation_media.router, prefix="/generation-media", tags=["Generation Media"])
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["Subscriptions"])
api_router.include_router(user_provider.router, prefix="/user-provider", tags=["User Provider"])

# Payment routes
api_router.include_router(credix.router, prefix="/payments", tags=["Payments"])
# Admin routes
api_router.include_router(admin_auth.router, prefix="/admin/auth", tags=["Admin Auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
api_router.include_router(admin_conversations.router, prefix="/admin", tags=["Admin Conversations"])
api_router.include_router(admin_preregistrations.router, prefix="/admin", tags=["Admin Preregistrations"])
api_router.include_router(admin_identity.router, prefix="/admin", tags=["Identity"])
api_router.include_router(admin_profile_images.router, prefix="/admin/profile-images", tags=["Admin Profile Images"])
api_router.include_router(admin_banners.router, prefix="/admin/banners", tags=["Admin Banners"])
api_router.include_router(admin_post.router, prefix="/admin/posts", tags=["Admin Posts"])
api_router.include_router(admin_events.router, prefix="/admin/events", tags=["Admin Events"])
api_router.include_router(admin_company.router, prefix="/admin/companies", tags=["Admin Companies"])
api_router.include_router(admin_notifications.router, prefix="/admin/notifications", tags=["Admin Notifications"])
# Debug routes
api_router.include_router(debug_email.router, prefix="/_debug", tags=["Debug"])