import os
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
from enum import Enum

from common.db_session import get_db
from common.logger import Logger


from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from models.social import (
    Follows,
    Likes,
    Bookmarks,
    PostViewsTracking,
    ProfileViewsTracking,
    UserRecommendations,
)
from models.posts import Posts
from models.post_categories import PostCategories
from models.payments import Payments
from models.prices import Prices
from models.plans import Plans, PostPlans

from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize


class BaseW(Enum):
    FOLLOW = 4.0

    LIKE_CREATOR_W = 3.0
    LIKE_CATEGORY_W = 2.0

    BOOKMARK_CREATOR_W = 5.0
    BOOKMARK_CATEGORY_W = 4.0

    VIEW_POST_CREATOR_W = 1.0
    VIEW_POST_CATEGORY_W = 1.0
    VIEW_PROFILE_CREATOR_W = 1.5

    PAY_SINGLE_CREATOR_W = 12.0
    PAY_SINGLE_CATEGORY_W = 10.0

    PAY_PLAN_CREATOR_W = 6.0
    PAY_PLAN_CATEGORY_W = 2.0


class CreatorsCategoriesRecommend:
    PAY_SUCCEEDED = 2
    ORDER_PLAN = 2
    ORDER_PRICE = 1
    WINDOW_DAYS = 30
    TAU_DAYS = 14.0
    TOP_K = 30
    CREATOR_SVD_K = 64
    CATEGORY_SVD_K = 32
    TYPE_CREATOR = 1
    TYPE_CATEGORY = 2

    def __init__(self, logger: Logger):
        self.db: Session = next(get_db())
        self.logger = logger
        self.MASK_FOLLOW_FOR_NEW_CREATOR = (
            os.environ.get("MASK_FOLLOW_FOR_NEW_CREATOR", "1") == "1"
        )

    def exec(self):
        creator_ds, category_ds, seen_creator, seen_category = self._build_data()

        top_new_creators, creator_meta = self._svd_top_new(
            agg=creator_ds,
            user_col="user_id",
            ent_col="creator_id",
            seen_map=seen_creator,
            n_components=CreatorsCategoriesRecommend.CREATOR_SVD_K,
            top_k=CreatorsCategoriesRecommend.TOP_K,
        )

        top_new_categories, category_meta = self._svd_top_new(
            agg=category_ds,
            user_col="user_id",
            ent_col="category_id",
            seen_map=seen_category,
            n_components=CreatorsCategoriesRecommend.CATEGORY_SVD_K,
            top_k=CreatorsCategoriesRecommend.TOP_K,
        )

        top_new_creators_payload = self._build_payload_df(
            top_new_creators, "creator_id", CreatorsCategoriesRecommend.TYPE_CREATOR
        )
        top_new_categories_payload = self._build_payload_df(
            top_new_categories, "category_id", CreatorsCategoriesRecommend.TYPE_CATEGORY
        )

        self._upsert_user_recommendations(top_new_creators_payload)
        self._upsert_user_recommendations(top_new_categories_payload)

    def _build_data(self):
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=self.WINDOW_DAYS)
        # Follows -> user x creator
        follows_stmt = select(
            Follows.follower_user_id.label("user_id"),
            Follows.creator_user_id.label("creator_id"),
        )
        follows_df = pd.read_sql(follows_stmt, self.db.bind)
        follows_df["w"] = BaseW.FOLLOW.value
        follows_df_uc = follows_df.groupby(["user_id", "creator_id"], as_index=False)[
            "w"
        ].sum()

        # Likes -> user x creator
        likes_stmt_uc = (
            select(
                Likes.user_id.label("user_id"),
                Posts.creator_user_id.label("creator_id"),
                Likes.created_at.label("ts"),
            )
            .join(Posts, Posts.id == Likes.post_id)
            .where(Likes.created_at >= window_start)
        )
        likes_df_uc = pd.read_sql(likes_stmt_uc, self.db.bind)
        likes_df_uc["w"] = BaseW.LIKE_CREATOR_W.value
        likes_df_uc_cat = likes_df_uc.groupby(
            ["user_id", "creator_id"], as_index=False
        )["w"].sum()

        # Likes -> user x category
        likes_stmt_cat = (
            select(
                Likes.user_id.label("user_id"),
                Likes.post_id.label("post_id"),
                PostCategories.category_id.label("category_id"),
                Likes.created_at.label("ts"),
            )
            .join(PostCategories, PostCategories.post_id == Likes.post_id)
            .where(Likes.created_at >= window_start)
        )

        likes_df_cat = pd.read_sql(likes_stmt_cat, self.db.bind)

        stmt_cat_count = select(
            PostCategories.post_id.label("post_id"),
            func.count(PostCategories.category_id).label("n_cat"),
        ).group_by(PostCategories.post_id)
        df_cat_count = pd.read_sql(stmt_cat_count, self.db.bind)

        likes_df_cat = likes_df_cat.merge(df_cat_count, on="post_id", how="left")
        likes_df_cat["n_cat"] = likes_df_cat["n_cat"].fillna(1).astype(int)

        likes_df_cat["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None)) - pd.to_datetime(likes_df_cat["ts"])
        ).dt.total_seconds() / 86400.0
        likes_df_cat["w_raw"] = BaseW.LIKE_CATEGORY_W.value * np.exp(
            -likes_df_cat["age_days"] / CreatorsCategoriesRecommend.TAU_DAYS
        )

        likes_df_cat["w"] = likes_df_cat["w_raw"] / likes_df_cat["n_cat"]

        likes_df_cat = likes_df_cat.groupby(["user_id", "category_id"], as_index=False)[
            "w"
        ].sum()

        # Bookmarks -> user x creator
        bookmark_stmt_uc = (
            select(
                Bookmarks.user_id.label("user_id"),
                Posts.creator_user_id.label("creator_id"),
                Bookmarks.created_at.label("ts"),
            )
            .join(Posts, Posts.id == Bookmarks.post_id)
            .where(Bookmarks.created_at >= window_start)
        )

        bookmark_df_uc = pd.read_sql(bookmark_stmt_uc, self.db.bind)

        bookmark_df_uc["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None))
            - pd.to_datetime(bookmark_df_uc["ts"])
        ).dt.total_seconds() / 86400.0
        bookmark_df_uc["w"] = BaseW.BOOKMARK_CREATOR_W.value * np.exp(
            -bookmark_df_uc["age_days"] / CreatorsCategoriesRecommend.TAU_DAYS
        )

        bookmark_df_uc = bookmark_df_uc.groupby(
            ["user_id", "creator_id"], as_index=False
        )["w"].sum()

        # Bookmarks -> user x category
        bookmark_stmt_cat = (
            select(
                Bookmarks.user_id.label("user_id"),
                Bookmarks.post_id.label("post_id"),
                PostCategories.category_id.label("category_id"),
                Bookmarks.created_at.label("ts"),
            )
            .join(PostCategories, PostCategories.post_id == Bookmarks.post_id)
            .where(Bookmarks.created_at >= window_start)
        )

        bookmark_df_cat = pd.read_sql(bookmark_stmt_cat, self.db.bind)

        bookmark_df_cat = bookmark_df_cat.merge(df_cat_count, on="post_id", how="left")
        bookmark_df_cat["n_cat"] = bookmark_df_cat["n_cat"].fillna(1).astype(int)

        bookmark_df_cat["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None))
            - pd.to_datetime(bookmark_df_cat["ts"])
        ).dt.total_seconds() / 86400.0
        bookmark_df_cat["w_raw"] = BaseW.BOOKMARK_CATEGORY_W.value * np.exp(
            -bookmark_df_cat["age_days"] / CreatorsCategoriesRecommend.TAU_DAYS
        )

        bookmark_df_cat["w"] = bookmark_df_cat["w_raw"] / bookmark_df_cat["n_cat"]

        bookmark_df_cat = bookmark_df_cat.groupby(
            ["user_id", "category_id"], as_index=False
        )["w"].sum()

        # PostViewsTracking -> user x creator
        pv_stmt_uc = (
            select(
                PostViewsTracking.viewer_user_id.label("user_id"),
                PostViewsTracking.post_id.label("post_id"),
                Posts.creator_user_id.label("creator_id"),
                PostViewsTracking.created_at.label("ts"),
                PostViewsTracking.watched_duration_sec.label("watched_time"),
                PostViewsTracking.video_duration_sec.label("total_time"),
            )
            .join(Posts, Posts.id == PostViewsTracking.post_id)
            .where(PostViewsTracking.created_at >= window_start)
        )

        pv_df_uc = pd.read_sql(pv_stmt_uc, self.db.bind)

        pv_df_uc["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None)) - pd.to_datetime(pv_df_uc["ts"])
        ).dt.total_seconds() / 86400.0
        pv_df_uc["decay"] = np.exp(-pv_df_uc["age_days"] / self.TAU_DAYS)

        if "watched_time" in pv_df_uc.columns and "total_time" in pv_df_uc.columns:
            denom = pv_df_uc["total_time"].replace(0, np.nan)
            pv_df_uc["watched_ratio"] = (
                (pv_df_uc["watched_time"] / denom).fillna(0.0).clip(0, 1)
            )

            pv_df_uc["q"] = 0.0
            pv_df_uc.loc[pv_df_uc["watched_ratio"] >= 0.10, "q"] = 0.5
            pv_df_uc.loc[pv_df_uc["watched_ratio"] >= 0.30, "q"] = 1.0
            pv_df_uc.loc[pv_df_uc["watched_ratio"] >= 0.70, "q"] = 1.5
        else:
            pv_df_uc["q"] = 1.0

        pv_df_uc["w"] = (
            BaseW.VIEW_POST_CREATOR_W.value * pv_df_uc["decay"] * pv_df_uc["q"]
        )

        pv_df_uc["day"] = pd.to_datetime(pv_df_uc["ts"]).dt.date
        pv_df_uc = pv_df_uc.sort_values(
            ["user_id", "post_id", "day", "w"], ascending=[True, True, True, False]
        ).drop_duplicates(subset=["user_id", "post_id", "day"], keep="first")

        pv_df_uc = pv_df_uc.groupby(["user_id", "creator_id"], as_index=False)[
            "w"
        ].sum()

        # PostViewsTracking -> user x category
        pv_stmt_cat = (
            select(
                PostViewsTracking.viewer_user_id.label("user_id"),
                PostViewsTracking.post_id.label("post_id"),
                PostCategories.category_id.label("category_id"),
                PostViewsTracking.created_at.label("ts"),
                PostViewsTracking.watched_duration_sec.label("watched_time"),
                PostViewsTracking.video_duration_sec.label("total_time"),
            )
            .join(PostCategories, PostCategories.post_id == PostViewsTracking.post_id)
            .where(PostViewsTracking.created_at >= window_start)
        )

        pv_df_cat = pd.read_sql(pv_stmt_cat, self.db.bind)

        pv_df_cat = pv_df_cat.merge(df_cat_count, on="post_id", how="left")
        pv_df_cat["n_cat"] = pv_df_cat["n_cat"].fillna(1).astype(int)

        pv_df_cat["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None)) - pd.to_datetime(pv_df_cat["ts"])
        ).dt.total_seconds() / 86400.0
        pv_df_cat["decay"] = np.exp(-pv_df_cat["age_days"] / self.TAU_DAYS)

        if "watched_time" in pv_df_cat.columns and "total_time" in pv_df_cat.columns:
            denom = pv_df_cat["total_time"].replace(0, np.nan)
            pv_df_cat["watched_ratio"] = (
                (pv_df_cat["watched_time"] / denom).fillna(0.0).clip(0, 1)
            )

            pv_df_cat["q"] = 0.0
            pv_df_cat.loc[pv_df_cat["watched_ratio"] >= 0.10, "q"] = 0.5
            pv_df_cat.loc[pv_df_cat["watched_ratio"] >= 0.30, "q"] = 1.0
            pv_df_cat.loc[pv_df_cat["watched_ratio"] >= 0.70, "q"] = 1.5
        else:
            pv_df_cat["q"] = 1.0

        pv_df_cat["w_raw"] = (
            BaseW.VIEW_POST_CATEGORY_W.value * pv_df_cat["decay"] * pv_df_cat["q"]
        )
        pv_df_cat["w"] = pv_df_cat["w_raw"] / pv_df_cat["n_cat"]

        pv_df_cat["day"] = pd.to_datetime(pv_df_cat["ts"]).dt.date
        pv_df_cat = pv_df_cat.sort_values(
            ["user_id", "post_id", "day", "w"], ascending=[True, True, True, False]
        ).drop_duplicates(subset=["user_id", "post_id", "day"], keep="first")

        pv_df_cat = pv_df_cat.groupby(["user_id", "category_id"], as_index=False)[
            "w"
        ].sum()

        # ProfileViewsTracking -> user x creator
        prof_stmt = select(
            ProfileViewsTracking.viewer_user_id.label("user_id"),
            ProfileViewsTracking.profile_user_id.label("creator_id"),
            ProfileViewsTracking.created_at.label("ts"),
        ).where(ProfileViewsTracking.created_at >= window_start)

        prof_df = pd.read_sql(prof_stmt, self.db.bind)

        prof_df["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None)) - pd.to_datetime(prof_df["ts"])
        ).dt.total_seconds() / 86400.0
        prof_df["w"] = BaseW.VIEW_PROFILE_CREATOR_W.value * np.exp(
            -prof_df["age_days"] / self.TAU_DAYS
        )

        prof_df["day"] = pd.to_datetime(prof_df["ts"]).dt.date
        prof_df = prof_df.sort_values(
            ["user_id", "creator_id", "day", "w"], ascending=[True, True, True, False]
        ).drop_duplicates(subset=["user_id", "creator_id", "day"], keep="first")

        prof_df_uc = prof_df.groupby(["user_id", "creator_id"], as_index=False)[
            "w"
        ].sum()

        # --- Payment single/price -> user x creator ---
        pay_price_stmt_uc = (
            select(
                Payments.buyer_user_id.label("user_id"),
                Posts.creator_user_id.label("creator_id"),
                Payments.created_at.label("ts"),
            )
            .join(Prices, Prices.id == cast(Payments.order_id, PG_UUID(as_uuid=True)))
            .join(Posts, Posts.id == Prices.post_id)
            .where(Payments.status == CreatorsCategoriesRecommend.PAY_SUCCEEDED)
            .where(Payments.order_type == CreatorsCategoriesRecommend.ORDER_PRICE)
            .where(Payments.created_at >= window_start)
        )

        pay_price_df_uc = pd.read_sql(pay_price_stmt_uc, self.db.bind)

        pay_price_df_uc["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None))
            - pd.to_datetime(pay_price_df_uc["ts"])
        ).dt.total_seconds() / 86400.0
        pay_price_df_uc["w"] = BaseW.PAY_SINGLE_CREATOR_W.value * np.exp(
            -pay_price_df_uc["age_days"] / CreatorsCategoriesRecommend.TAU_DAYS
        )

        pay_price_df_uc = pay_price_df_uc.groupby(
            ["user_id", "creator_id"], as_index=False
        )["w"].sum()

        # --- Payment single/price -> user x category ---
        pay_price_stmt_cat = (
            select(
                Payments.buyer_user_id.label("user_id"),
                Prices.post_id.label("post_id"),
                PostCategories.category_id.label("category_id"),
                Payments.created_at.label("ts"),
            )
            .join(Prices, Prices.id == cast(Payments.order_id, PG_UUID(as_uuid=True)))
            .join(PostCategories, PostCategories.post_id == Prices.post_id)
            .where(Payments.status == CreatorsCategoriesRecommend.PAY_SUCCEEDED)
            .where(Payments.order_type == CreatorsCategoriesRecommend.ORDER_PRICE)
            .where(Payments.created_at >= window_start)
        )

        pay_price_df_cat = pd.read_sql(pay_price_stmt_cat, self.db.bind)

        pay_price_df_cat = pay_price_df_cat.merge(
            df_cat_count, on="post_id", how="left"
        )
        pay_price_df_cat["n_cat"] = pay_price_df_cat["n_cat"].fillna(1).astype(int)

        pay_price_df_cat["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None))
            - pd.to_datetime(pay_price_df_cat["ts"])
        ).dt.total_seconds() / 86400.0
        pay_price_df_cat["w_raw"] = BaseW.PAY_SINGLE_CATEGORY_W.value * np.exp(
            -pay_price_df_cat["age_days"] / CreatorsCategoriesRecommend.TAU_DAYS
        )
        pay_price_df_cat["w"] = pay_price_df_cat["w_raw"] / pay_price_df_cat["n_cat"]

        pay_price_df_cat = pay_price_df_cat.groupby(
            ["user_id", "category_id"], as_index=False
        )["w"].sum()

        # --- Payment plan -> user x creator ---
        pay_plan_stmt_uc = (
            select(
                Payments.buyer_user_id.label("user_id"),
                Plans.creator_user_id.label("creator_id"),
                Payments.created_at.label("ts"),
            )
            .join(Plans, Plans.id == cast(Payments.order_id, PG_UUID(as_uuid=True)))
            .where(Payments.status == CreatorsCategoriesRecommend.PAY_SUCCEEDED)
            .where(Payments.order_type == CreatorsCategoriesRecommend.ORDER_PLAN)
            .where(Payments.created_at >= window_start)
        )

        pay_plan_df_uc = pd.read_sql(pay_plan_stmt_uc, self.db.bind)

        pay_plan_df_uc["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None))
            - pd.to_datetime(pay_plan_df_uc["ts"])
        ).dt.total_seconds() / 86400.0
        pay_plan_df_uc["w"] = BaseW.PAY_PLAN_CREATOR_W.value * np.exp(
            -pay_plan_df_uc["age_days"] / CreatorsCategoriesRecommend.TAU_DAYS
        )

        pay_plan_df_uc = pay_plan_df_uc.groupby(
            ["user_id", "creator_id"], as_index=False
        )["w"].sum()

        # --- Payment plan -> user x category (dilute) ---
        pay_plan_stmt_cat = (
            select(
                Payments.buyer_user_id.label("user_id"),
                Payments.order_id.label("plan_id"),
                PostCategories.category_id.label("category_id"),
                Payments.created_at.label("ts"),
            )
            .join(
                PostPlans,
                PostPlans.plan_id == cast(Payments.order_id, PG_UUID(as_uuid=True)),
            )
            .join(PostCategories, PostCategories.post_id == PostPlans.post_id)
            .where(Payments.status == CreatorsCategoriesRecommend.PAY_SUCCEEDED)
            .where(Payments.order_type == CreatorsCategoriesRecommend.ORDER_PLAN)
            .where(Payments.created_at >= window_start)
        )

        pay_plan_df_cat = pd.read_sql(pay_plan_stmt_cat, self.db.bind)

        pay_plan_df_cat = pay_plan_df_cat.drop_duplicates(
            subset=["user_id", "plan_id", "category_id", "ts"]
        )

        plan_cat_cnt = (
            pay_plan_df_cat.groupby(["user_id", "plan_id", "ts"], as_index=False)[
                "category_id"
            ]
            .nunique()
            .rename(columns={"category_id": "n_cat_in_plan"})
        )

        pay_plan_df_cat = pay_plan_df_cat.merge(
            plan_cat_cnt, on=["user_id", "plan_id", "ts"], how="left"
        )
        pay_plan_df_cat["n_cat_in_plan"] = (
            pay_plan_df_cat["n_cat_in_plan"].fillna(1).astype(int)
        )

        pay_plan_df_cat["age_days"] = (
            pd.Timestamp(now.replace(tzinfo=None))
            - pd.to_datetime(pay_plan_df_cat["ts"])
        ).dt.total_seconds() / 86400.0

        pay_plan_df_cat["w_raw"] = BaseW.PAY_PLAN_CATEGORY_W.value * np.exp(
            -pay_plan_df_cat["age_days"] / CreatorsCategoriesRecommend.TAU_DAYS
        )

        pay_plan_df_cat["w"] = (
            pay_plan_df_cat["w_raw"] / pay_plan_df_cat["n_cat_in_plan"]
        )

        pay_plan_df_cat = pay_plan_df_cat.groupby(
            ["user_id", "category_id"], as_index=False
        )["w"].sum()

        creator_train = pd.concat(
            [
                follows_df_uc,
                likes_df_uc_cat,
                bookmark_df_uc,
                pv_df_uc,
                prof_df_uc,
                pay_price_df_uc,
                pay_plan_df_uc,
            ],
            ignore_index=True,
        )

        creator_train = creator_train.groupby(
            ["user_id", "creator_id"], as_index=False
        )["w"].sum()

        creator_train = (
            pd.concat(
                [
                    follows_df_uc,
                    likes_df_uc_cat,
                    bookmark_df_uc,
                    pv_df_uc,
                    prof_df_uc,
                    pay_price_df_uc,
                    pay_plan_df_uc,
                ],
                ignore_index=True,
            )
            .groupby(["user_id", "creator_id"], as_index=False)["w"]
            .sum()
        )

        creator_train = creator_train[creator_train["w"] > 0]

        category_train = (
            pd.concat(
                [
                    likes_df_cat,
                    bookmark_df_cat,
                    pv_df_cat,
                    pay_price_df_cat,
                    pay_plan_df_cat,
                ],
                ignore_index=True,
            )
            .groupby(["user_id", "category_id"], as_index=False)["w"]
            .sum()
        )

        category_train = category_train[category_train["w"] > 0]

        seen_category = (
            pd.concat(
                [
                    likes_df_cat,
                    bookmark_df_cat,
                    pv_df_cat,
                    pay_price_df_cat,
                    pay_plan_df_cat,
                ],
                ignore_index=True,
            )
            .groupby("user_id")["category_id"]
            .apply(set)
            .to_dict()
        )

        creator_seen_parts = [
            likes_df_uc_cat,
            bookmark_df_uc,
            pv_df_uc,
            prof_df_uc,
            pay_price_df_uc,
            pay_plan_df_uc,
        ]
        if self.MASK_FOLLOW_FOR_NEW_CREATOR:
            creator_seen_parts.append(follows_df_uc)

        seen_creator = (
            pd.concat(creator_seen_parts, ignore_index=True)
            .groupby("user_id")["creator_id"]
            .apply(set)
            .to_dict()
        )

        return creator_train, category_train, seen_creator, seen_category

    def _svd_top_new(
        self,
        agg: pd.DataFrame,
        user_col: str,
        ent_col: str,
        seen_map: dict,
        n_components: int = 64,
        top_k: int = 30,
        user_batch: int = 512,
    ):
        if agg.empty:
            return pd.DataFrame(columns=[user_col, ent_col, "rank", "score"]), {
                "n_users": 0,
                "n_ents": 0,
                "k": 0,
            }

        users = agg[user_col].unique()
        ents = agg[ent_col].unique()

        u2i = {u: i for i, u in enumerate(users)}
        e2j = {e: j for j, e in enumerate(ents)}

        rows = agg[user_col].map(u2i).to_numpy()
        cols = agg[ent_col].map(e2j).to_numpy()
        data = agg["w"].to_numpy().astype(np.float32)

        X = csr_matrix((data, (rows, cols)), shape=(len(users), len(ents)))

        tfidf = TfidfTransformer(
            norm=None, use_idf=True, smooth_idf=True, sublinear_tf=True
        )
        X_t = tfidf.fit_transform(X)

        min_dim = min(X_t.shape)
        k = min(n_components, max(1, min_dim - 1))
        svd = TruncatedSVD(n_components=k, random_state=42)

        U = svd.fit_transform(X_t)  # (n_users, k)
        V = svd.components_.T  # (n_ents, k)

        U = normalize(U)
        V = normalize(V)

        out = []

        n_users = len(users)
        n_ents = len(ents)

        for start in range(0, n_users, user_batch):
            end = min(start + user_batch, n_users)
            Ub = U[start:end]  # (b, k)
            Sb = Ub @ V.T  # (b, n_ents)

            for bi, ui in enumerate(range(start, end)):
                u = users[ui]
                s = Sb[bi]

                # mask seen
                for ent in seen_map.get(u, set()):
                    j = e2j.get(ent)
                    if j is not None:
                        s[j] = -np.inf

                finite = np.isfinite(s)
                if finite.sum() == 0:
                    continue

                kk = min(top_k, int(finite.sum()))
                idx = np.argpartition(-s, kth=kk - 1)[:kk]
                idx = idx[np.argsort(-s[idx])]

                for rank, j in enumerate(idx, 1):
                    out.append(
                        {
                            user_col: u,
                            ent_col: ents[j],
                            "rank": rank,
                            "score": float(s[j]),
                        }
                    )

        return pd.DataFrame(out), {
            "tfidf": tfidf,
            "svd": svd,
            "users": users,
            "ents": ents,
            "n_users": n_users,
            "n_ents": n_ents,
            "k": k,
        }

    def _build_payload_df(
        self, df: pd.DataFrame, id_col: str, reco_type: int
    ) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["user_id", "type", "payload"])

        df2 = df.sort_values(["user_id", "rank"]).copy()

        payload_df = (
            df2.groupby("user_id")
            .apply(
                lambda g: [
                    {
                        "id": str(getattr(x, id_col)),
                        "rank": int(x.rank),
                        "score": float(x.score),
                    }
                    for x in g.itertuples(index=False)
                ]
            )
            .reset_index(name="payload")
        )
        payload_df["type"] = reco_type
        return payload_df[["user_id", "type", "payload"]]

    def _upsert_user_recommendations(self, payload_df: pd.DataFrame):
        try:
            if payload_df.empty:
                return

            table = UserRecommendations.__table__

            records = [
                {
                    "user_id": r.user_id,
                    "type": int(r.type),
                    "payload": r.payload,
                    "updated_at": datetime.now(timezone.utc),
                }
                for r in payload_df.itertuples(index=False)
            ]

            stmt = insert(table).values(records)

            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "type"],
                set_={
                    "payload": stmt.excluded.payload,
                },
            )

            self.db.execute(stmt)
            self.db.commit()
        except Exception as e:
            self.logger.error(f"Error upserting user recommendations: {e}")
            self.db.rollback()
            return
