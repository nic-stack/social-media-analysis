"""Build the public dashboard (no captions, links, IDs, exact dates or follower counts).

Usage: python build_dashboard.py <project_dir> <dashboard_template.html> <chart.umd.min.js> <out.html>
"""
import datetime
import json
import os
import random
import sys

import numpy as np
import pandas as pd

P, TPL, CHARTJS, OUT = sys.argv[1:5]
TAB = os.path.join(P, "outputs", "tables")
NETS = ["instagram", "linkedin", "facebook"]
d = pd.read_csv(os.path.join(P, "prepared", "posts_prepared.csv"), parse_dates=["published_at"])
d["age"] = (pd.Timestamp("2026-11-11") - d.published_at).dt.days
f = d[d.in_feed_analysis & (d.age >= 14)].copy()
f.loc[f.network.eq("facebook") & f.zero_impressions, "impressions"] = np.nan
f["inter"] = f[["likes", "comments", "shares"]].sum(axis=1, min_count=1)


def num(v):
    return None if pd.isna(v) else (int(v) if float(v).is_integer() else round(float(v), 4))


# random group numbers replace the scheduling tool's IDs; only multi-platform groups keep one
gid = f.publication_group_id
multi = [g for g, n in gid.value_counts().items() if n > 1]
random.SystemRandom().shuffle(multi)
code = {g: i + 1 for i, g in enumerate(multi)}
gtopic = f.dropna(subset=["publication_group_id"]).groupby("publication_group_id").topic.agg(lambda x: x.mode().iloc[0])
posts = [{
    "g": code.get(r.publication_group_id), "n": r.network, "m": r.month, "t": r.topic,
    "gt": gtopic.get(r.publication_group_id) if isinstance(r.publication_group_id, str) else None,
    "tc": r.topic_confidence, "s": bool(r.student_focused), "lk": bool(r.campus_life), "f": r.format,
    "i": num(r.impressions), "x": num(r.inter), "r": num(r.reach), "ck": num(r.clicks),
} for r in f.itertuples()]
# random order within each month so row order does not reveal the publishing order
random.SystemRandom().shuffle(posts)
posts.sort(key=lambda p: p["m"])

# timing is shared only as aggregates
f["wd"] = f.weekday.where(~f.weekday.isin(["Saturday", "Sunday"]), "Weekend")
f["dp"] = np.select([f.hour < 12, f.hour < 15, f.hour < 18], [0, 1, 2], default=3)
days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Weekend"]


def agg(x):
    return {"n": int(len(x)), "v": num(x.impressions.median()) if len(x) else None}


def cell(x):
    c = agg(x)
    return c if c["n"] >= 3 else {"n": c["n"], "v": None}  # hide near-individual values


timing = {n: {"wd": {w: agg(f[f.network.eq(n) & f.wd.eq(w)]) for w in days},
              "grid": {w: [cell(f[f.network.eq(n) & f.wd.eq(w) & f.dp.eq(k)]) for k in range(4)] for w in days}} for n in NETS}

g = pd.read_csv(os.path.join(TAB, "step5_follower_growth_monthly.csv"))
growth = {n: {"months": list(x.month), "rate": [num(v) for v in x["growth_rate_%"]]} for n, x in g.groupby("network")}
us = pd.read_csv(os.path.join(TAB, "step5_us_follower_share_monthly.csv"), index_col=0)
us = us[us.index < "2026-11"]
data = {"posts": posts, "growth": growth, "timing": timing,
        "us": {"months": list(us.index), "facebook": [num(v) for v in us.facebook], "instagram": [num(v) for v in us.instagram]},
        "built": datetime.date.today().isoformat()}
js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
tpl = open(TPL, encoding="utf-8").read()
chart = open(CHARTJS, encoding="utf-8").read().replace("</script", "<\\/script")
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
open(OUT, "w", encoding="utf-8").write(tpl.replace("/*__CHARTJS__*/", chart).replace("/*__DATA__*/null", js))
print("posts", len(posts), "keys", sorted(posts[0]), "matched groups", len(code))
