import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize
from icecream import ic
now = pd.Timestamp("2026-01-23 09:00:00")  

events = pd.DataFrame(
    [
        # user u1
        ("u1", "p1", "view",     now - pd.Timedelta(days=2)),
        ("u1", "p1", "like",     now - pd.Timedelta(days=2)),
        ("u1", "p2", "view",     now - pd.Timedelta(days=5)),
        ("u1", "p3", "purchase", now - pd.Timedelta(days=10)),

        # user u2
        ("u2", "p2", "view",     now - pd.Timedelta(days=1)),
        ("u2", "p2", "like",     now - pd.Timedelta(days=1)),
        ("u2", "p4", "purchase", now - pd.Timedelta(days=7)),
        ("u2", "p5", "view",     now - pd.Timedelta(days=12)),

        # user u3
        ("u3", "p6", "view",     now - pd.Timedelta(days=3)),
        ("u3", "p6", "like",     now - pd.Timedelta(days=3)),
        ("u3", "p5", "view",     now - pd.Timedelta(days=4)),
        ("u3", "p7", "purchase", now - pd.Timedelta(days=20)),

        # user u4
        ("u4", "p8", "view",     now - pd.Timedelta(days=2)),
        ("u4", "p8", "purchase", now - pd.Timedelta(days=2)),
        ("u4", "p3", "view",     now - pd.Timedelta(days=6)),
        ("u4", "p1", "view",     now - pd.Timedelta(days=9)),
    ],
    columns=["user_id", "post_id", "event_type", "ts"]
)

post_map = pd.DataFrame(
    [
        ("p1", "cat_A", "cr_1"),
        ("p2", "cat_A", "cr_2"),
        ("p3", "cat_B", "cr_1"),
        ("p4", "cat_B", "cr_3"),
        ("p5", "cat_C", "cr_2"),
        ("p6", "cat_C", "cr_4"),
        ("p7", "cat_D", "cr_5"),
        ("p8", "cat_D", "cr_3"),
    ],
    columns=["post_id", "category_id", "creator_id"]
)

df = events.merge(post_map, on="post_id", how="left")

BASE_W = {"purchase": 10.0, "follow": 4.0, "like": 3.0, "view": 1.0}
TAU_DAYS = 14.0

age_days = (now - df["ts"]).dt.total_seconds() / 86400.0
df["base_w"] = df["event_type"].map(BASE_W).fillna(0.0).astype(float)
df["decay"] = np.exp(-age_days / TAU_DAYS)
df["w"] = df["base_w"] * df["decay"]

agg_cat = df.groupby(["user_id", "category_id"], as_index=False)["w"].sum()
agg_cr  = df.groupby(["user_id", "creator_id"],  as_index=False)["w"].sum()

ic("\n=== Training dataset: User×Category (agg 30d) ===")
ic(agg_cat.sort_values(["user_id", "w"], ascending=[True, False]).to_string(index=False))

ic("\n=== Training dataset: User×Creator (agg 30d) ===")
ic(agg_cr.sort_values(["user_id", "w"], ascending=[True, False]).to_string(index=False))

def train_and_top_new(agg: pd.DataFrame, user_col: str, ent_col: str, n_components: int = 4, top_k: int = 3):
    ic(agg)
    users = agg[user_col].unique()
    ents = agg[ent_col].unique()

    u2i = {u: i for i, u in enumerate(users)}
    e2j = {e: j for j, e in enumerate(ents)}

    rows = agg[user_col].map(u2i).to_numpy()
    cols = agg[ent_col].map(e2j).to_numpy()
    data = agg["w"].to_numpy().astype(np.float32)

    X = csr_matrix((data, (rows, cols)), shape=(len(users), len(ents)))

    tfidf = TfidfTransformer(norm=None, use_idf=True, smooth_idf=True, sublinear_tf=True)
    X_t = tfidf.fit_transform(X)

    k = min(n_components, min(X_t.shape) - 1)  # avoid error when matrix is too small
    svd = TruncatedSVD(n_components=k, random_state=42)
    U = svd.fit_transform(X_t)    # user vectors (n_users, k)
    V = svd.components_.T         # entity vectors (n_ents, k)

    # normalize to dot ~ cosine
    U = normalize(U)
    V = normalize(V)

    scores = U @ V.T  # (n_users, n_ents)

    # seen entities in 30 days (to exclude "new")
    seen = {u: set(sub[ent_col].tolist()) for u, sub in agg.groupby(user_col)}

    # output top new
    out_rows = []
    for ui, u in enumerate(users):
        s = scores[ui].copy()

        # mask seen
        for ent in seen[u]:
            s[e2j[ent]] = -np.inf

        # get top_k
        finite_mask = np.isfinite(s)
        if finite_mask.sum() == 0:
            continue

        kk = min(top_k, finite_mask.sum())
        idx = np.argpartition(-s, kth=kk - 1)[:kk]
        idx = idx[np.argsort(-s[idx])]

        for rank, j in enumerate(idx, 1):
            out_rows.append({user_col: u, ent_col: ents[j], "rank": rank, "score": float(s[j])})

    return pd.DataFrame(out_rows)

top_new_cat = train_and_top_new(agg_cat, "user_id", "category_id", n_components=4, top_k=3)
top_new_cr  = train_and_top_new(agg_cr,  "user_id", "creator_id",  n_components=4, top_k=3)

ic("\n=== RESULT: Top NEW Categories (exclude seen 30d) ===")
ic(top_new_cat.sort_values(["user_id", "rank"]).to_string(index=False))

ic("\n=== RESULT: Top NEW Creators (exclude seen 30d) ===")
ic(top_new_cr.sort_values(["user_id", "rank"]).to_string(index=False))
