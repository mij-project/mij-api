from collections import deque
import json
import base64
import secrets
import random
from uuid import UUID
from typing import Optional
from sqlalchemy.orm import Session
from logging import Logger
from app.core.logger import Logger as CoreLogger
from app.crud.post_crud import PostsCrud
from app.crud.social_crud import SocialCrud
from app.crud.user_recommendations_crud import UserRecommendationsCrud
from app.models.user import Users

class ShortsDomain:
    MAX_SEEN = 120
    CREATOR_CAP = 2
    RATIO_REC = 0.8
    BATCH_REC = 160
    BATCH_FOL = 10
    BATCH_SHUF = 120
    MAX_ROUNDS = 4

    def __init__(self, db: Session):
        self.db: Session = db
        self.logger: Logger = CoreLogger.get_logger()
        self.posts_crud: PostsCrud = PostsCrud(db=db)
        self.user_recs_crud: UserRecommendationsCrud = UserRecommendationsCrud(db=db)
        self.social_crud: SocialCrud = SocialCrud(db=db)

    def __shuffle(self, seed: str, xs: list):
        ys = list(xs or [])
        r = random.Random(seed)
        r.shuffle(ys)
        return ys

    def __dedupe_uuid(self, xs: list[UUID]) -> list[UUID]:
        seen = set()
        out = []
        for x in xs or []:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    def __b64e(self, obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8")

    def __b64d(self, s: str) -> dict:
        raw = base64.urlsafe_b64decode(s.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))

    def __trim_tail(self, xs: list[str], n: int) -> list[str]:
        return xs[-n:] if len(xs) > n else xs

    def __safe_uuid_list(self, xs: list[str]) -> list[UUID]:
        out = []
        for x in xs or []:
            try:
                out.append(UUID(x))
            except Exception:
                pass
        return out

    def __extract_ids(self, payload: list[dict], keys: tuple[str, ...]) -> list[str]:
        out = []
        for item in payload or []:
            if not isinstance(item, dict):
                continue
            for k in keys:
                v = item.get(k)
                if isinstance(v, str) and v:
                    out.append(v)
                    break
        seen = set()
        uniq = []
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq

    def __apply_creator_cap(self, details: list[dict]) -> list[dict]:
        cnt = {}
        out = []
        for it in details or []:
            c = it.get("creator")
            cid = c.get("user_id")
            if not cid:
                out.append(it)
                continue
            cnt[cid] = cnt.get(cid, 0) + 1
            if cnt[cid] <= self.CREATOR_CAP:
                out.append(it)
        return out

    def __reorder_recent_max_consecutive(
        self,
        rows: list[tuple[UUID, UUID, int]],  # (pid, cid, k)
        need: int,
        last_cid: Optional[UUID],
        run: int,
        max_consecutive: int = 2,
    ) -> tuple[list[tuple[UUID, UUID]], Optional[UUID], int]:
        """
        Return (picked_pairs, new_last_cid, new_run)
        picked_pairs: [(pid, cid), ...]
        """
        if not rows or need <= 0:
            return [], last_cid, run

        buckets: dict[UUID, deque[tuple[int, UUID]]] = {}
        for pid, cid, k in rows:
            buckets.setdefault(cid, deque()).append((k, pid))

        out: list[tuple[UUID, UUID]] = []

        while len(out) < need:
            candidates = []
            for cid, q in buckets.items():
                if not q:
                    continue
                k, pid = q[0]
                candidates.append((k, pid, cid))

            if not candidates:
                break

            candidates.sort(reverse=True, key=lambda x: (x[0], str(x[1])))

            chosen = None
            if last_cid is not None and run >= max_consecutive:
                for k, pid, cid in candidates:
                    if cid != last_cid:
                        chosen = (k, pid, cid)
                        break

            if chosen is None:
                chosen = candidates[0]

            _, pid, cid = chosen
            buckets[cid].popleft()
            out.append((pid, cid))

            if cid == last_cid:
                run += 1
            else:
                last_cid = cid
                run = 1

        return out, last_cid, run

    def get_shorts_recommend(
        self,
        user: Optional[Users] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ):
        # --- cursor state ---
        if cursor:
            c = self.__b64d(cursor)
            seed = c["seed"]
            rec_cur = c.get("rec") or {}
            shuf_cur = c.get("shuf") or {}
            seen = c.get("seen") or []
        else:
            seed = secrets.token_urlsafe(12)
            rec_cur = {}
            shuf_cur = {}
            seen = []

        seen_uuid = self.__safe_uuid_list(seen)

        rec_last_k = rec_cur.get("last_k")
        rec_last_id = rec_cur.get("last_id")
        shuf_last_k = shuf_cur.get("last_k")
        shuf_last_id = shuf_cur.get("last_id")

        user_id = user.id if user else None
        # --- load recs (2 types) ---
        creator_ids: list[UUID] = []
        category_ids: list[UUID] = []
        has_rec = False

        if user_id:
            recs = self.user_recs_crud.get_user_recommendations(user_id=user_id)
            creator_raw = self.__extract_ids(recs.get("creators") or [], keys=("id", "creator_id", "user_id"))
            category_raw = self.__extract_ids(recs.get("categories") or [], keys=("id", "category_id"))
            creator_ids = self.__safe_uuid_list(creator_raw)
            category_ids = self.__safe_uuid_list(category_raw)
            has_rec = bool(creator_ids or category_ids)

        # --- mix loop ---
        picked_ids: list[UUID] = []
        picked_set = set(seen_uuid)

        next_rec_last_k = rec_last_k
        next_rec_last_id = UUID(rec_last_id) if isinstance(rec_last_id, str) else rec_last_id
        next_shuf_last_k = shuf_last_k
        next_shuf_last_id = UUID(shuf_last_id) if isinstance(shuf_last_id, str) else shuf_last_id
        rounds = 0
        while len(picked_ids) < limit and rounds < self.MAX_ROUNDS:
            rounds += 1

            need = limit - len(picked_ids)
            target_rec = int(round(limit * self.RATIO_REC))
            target_rec = max(0, min(target_rec, limit))

            # exclude = seen + already picked
            exclude_ids = list(picked_set)

            rec_ids: list[UUID] = []
            shuf_ids: list[UUID] = []

            if user_id and has_rec:
                rec_ids, next_rec_last_k, next_rec_last_id = self.posts_crud.get_list_recommend_post_ids(
                    user_id=user_id,
                    creator_ids=creator_ids,
                    category_ids=category_ids,
                    limit=self.BATCH_REC,
                    exclude_ids=exclude_ids,
                    last_k=next_rec_last_k,
                    last_id=next_rec_last_id,
                )

            shuf_ids, next_shuf_last_k, next_shuf_last_id = self.posts_crud.get_list_shuffle_post_ids(
                user_id=user_id,
                limit=self.BATCH_SHUF,
                exclude_ids=exclude_ids,
                last_k=next_shuf_last_k,
                last_id=next_shuf_last_id,
            )

            if not rec_ids and not shuf_ids:
                return self.get_shorts_recommend(user=user, limit=limit)

            # deterministic shuffle per round
            rec_ids = self.__shuffle(f"{seed}:rec:{rounds}", rec_ids)
            shuf_ids = self.__shuffle(f"{seed}:shuf:{rounds}", shuf_ids)

            # take by ratio
            take_rec = 0
            if user_id and has_rec:
                remain_rec_quota = max(0, target_rec - len([x for x in picked_ids]))
                take_rec = min(remain_rec_quota, need, len(rec_ids))

            take_shuf = min(need - take_rec, len(shuf_ids))

            candidates = rec_ids[:take_rec] + shuf_ids[:take_shuf]

            # fill if still need
            if len(candidates) < need:
                extra = rec_ids[take_rec:] + shuf_ids[take_shuf:]
                candidates.extend(extra[: (need - len(candidates))])

            # add to picked with dedupe
            for pid in candidates:
                if pid in picked_set:
                    continue
                picked_ids.append(pid)
                picked_set.add(pid)
                if len(picked_ids) >= limit:
                    break

        picked_ids = self.__dedupe_uuid(picked_ids)[:limit]

        # --- update seen + cursor ---
        new_seen = [str(x) for x in (seen_uuid + picked_ids)]
        new_seen = self.__trim_tail(new_seen, self.MAX_SEEN)

        next_cursor = self.__b64e(
            {
                "seed": seed,
                "rec": {
                    "last_k": next_rec_last_k,
                    "last_id": str(next_rec_last_id) if next_rec_last_id else None,
                },
                "shuf": {
                    "last_k": next_shuf_last_k,
                    "last_id": str(next_shuf_last_id) if next_shuf_last_id else None,
                },
                "seen": new_seen,
            }
        )

        return {
            "items": picked_ids,
            "cursor": next_cursor,
            "seed": seed,
        }

    def get_shorts_follows(
        self,
        user: Optional["Users"] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ):
        user_id = user.id if user else None
        if not user_id:
            return {"items": [], "cursor": None, "seed": None}

        follows = self.social_crud.get_follows_by_user_id(user_id=user_id)
        if not follows:
            return {"items": [], "cursor": None, "seed": None}

        creator_ids: list[UUID] = []
        for x in follows:
            try:
                creator_ids.append(x if isinstance(x, UUID) else UUID(str(x)))
            except Exception:
                pass

        creator_ids = self.__dedupe_uuid(creator_ids)
        if not creator_ids:
            return {"items": [], "cursor": None, "seed": None}

        attempts = 0
        cur = cursor

        while attempts < 2:
            attempts += 1

            if cur:
                c = self.__b64d(cur)
                seed = c.get("seed") or secrets.token_urlsafe(12)
                fol_cur = c.get("fol") or {}
                seen = c.get("seen") or []
                head_done = bool(c.get("head"))

                mc = c.get("mc") or {}
                last_cid = UUID(mc["last_cid"]) if isinstance(mc.get("last_cid"), str) and mc["last_cid"] else None
                run = int(mc.get("run") or 0)
            else:
                seed = secrets.token_urlsafe(12)
                fol_cur = {}
                seen = []
                head_done = False
                last_cid = None
                run = 0

            seen_uuid = self.__safe_uuid_list(seen)
            picked_set = set(seen_uuid)
            picked_pairs: list[tuple[UUID, UUID]] = []  # (pid, cid)

            # (A) HEAD: Get latest post per creator
            if not head_done:
                head_rows = self.posts_crud.get_latest_posts_per_creators_rows(
                    creator_ids=creator_ids,
                    limit=min(limit, len(creator_ids)),
                    exclude_ids=list(picked_set),
                )
                for pid, cid, _k in head_rows:
                    if pid in picked_set:
                        continue
                    picked_pairs.append((pid, cid))
                    picked_set.add(pid)

                    if cid == last_cid:
                        run += 1
                    else:
                        last_cid = cid
                        run = 1

                    if len(picked_pairs) >= limit:
                        break

            # (B) STREAM: keyset newest-first + consecutive > 2
            fol_last_k = fol_cur.get("last_k")
            fol_last_id = fol_cur.get("last_id")

            next_last_k = int(fol_last_k) if isinstance(fol_last_k, int) else None
            next_last_id = UUID(fol_last_id) if isinstance(fol_last_id, str) and fol_last_id else None

            rounds = 0
            while len(picked_pairs) < limit and rounds < self.MAX_ROUNDS:
                rounds += 1
                need = limit - len(picked_pairs)

                rows, next_last_k, next_last_id = self.posts_crud.get_list_follow_post_rows(
                    creator_ids=creator_ids,
                    limit=self.BATCH_FOL,
                    exclude_ids=list(picked_set),
                    last_k=next_last_k,
                    last_id=next_last_id,
                )

                if not rows:
                    break

                selected, last_cid, run = self.__reorder_recent_max_consecutive(
                    rows=rows,
                    need=need,
                    last_cid=last_cid,
                    run=run,
                    max_consecutive=2,
                )
                if not selected:
                    break

                for pid, cid in selected:
                    if pid in picked_set:
                        continue
                    picked_pairs.append((pid, cid))
                    picked_set.add(pid)
                    if len(picked_pairs) >= limit:
                        break

            picked_ids = [pid for pid, _ in picked_pairs]
            picked_ids = self.__dedupe_uuid(picked_ids)[:limit]

            if not picked_ids:
                if cur:
                    cur = None
                    continue
                return {"items": [], "cursor": None, "seed": seed}

            new_seen = [str(x) for x in (seen_uuid + picked_ids)]
            new_seen = self.__trim_tail(new_seen, self.MAX_SEEN)

            next_cursor = self.__b64e(
                {
                    "seed": seed,
                    "head": True,
                    "fol": {
                        "last_k": next_last_k,
                        "last_id": str(next_last_id) if next_last_id else None,
                    },
                    "mc": {
                        "last_cid": str(last_cid) if last_cid else None,
                        "run": run,
                    },
                    "seen": new_seen,
                }
            )

            return {
                "items": [str(x) for x in picked_ids],
                "cursor": next_cursor,
                "seed": seed,
            }

        return {"items": [], "cursor": None, "seed": None}
