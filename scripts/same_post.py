"""Same-post cross-platform comparison + topic x platform summary.
Usage: python -I same_post.py <project_dir>
Matches posts via Vista Social publication_group_id (same content published to several networks).
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

P = sys.argv[1]
TAB = os.path.join(P, "outputs", "tables")
CH = os.path.join(P, "outputs", "charts")
d = pd.read_csv(os.path.join(P, "prepared", "posts_prepared.csv"), parse_dates=["published_at"])
d["age"] = (pd.Timestamp("2026-11-11") - d.published_at).dt.days
f = d[d.in_feed_analysis & (d.age >= 14) & d.publication_group_id.notna()].copy()
f.loc[f.network.eq("facebook") & f.zero_impressions, ["impressions"]] = np.nan
# common interaction measure for all platforms (exclude IG saves for comparability)
f["inter_lcs"] = f[["likes", "comments", "shares"]].sum(axis=1, min_count=1)
f["rate_lcs"] = f.inter_lcs / f.impressions.where(f.impressions > 0) * 100

NETS = ["instagram", "linkedin", "facebook"]
wide = f.pivot_table(index="publication_group_id", columns="network",
                     values=["impressions", "inter_lcs", "rate_lcs", "likes", "comments", "shares"], aggfunc="first")
# group-level topic: most common topic among the group's posts (they share a caption)
gtopic = f.groupby("publication_group_id").topic.agg(lambda s: s.mode().iloc[0])
gdate = f.groupby("publication_group_id").published_at.min()
gfmt = f.pivot_table(index="publication_group_id", columns="network", values="format", aggfunc="first")
ghead = f.groupby("publication_group_id").headline.first()

pairs = []
for a, b in [("instagram", "linkedin"), ("instagram", "facebook"), ("linkedin", "facebook")]:
    for m, label in [("impressions", "Impressions"), ("inter_lcs", "Interactions (likes+comments+shares)"), ("rate_lcs", "Interaction rate % (÷ impressions)")]:
        x = wide[(m, a)] if (m, a) in wide else None
        y = wide[(m, b)] if (m, b) in wide else None
        ok = x.notna() & y.notna()
        x, y = x[ok], y[ok]
        p = stats.wilcoxon(x, y).pvalue if len(x) >= 10 else np.nan
        pairs.append({
            "comparison": f"{a} vs {b}", "metric": label, "matched_posts": int(ok.sum()),
            f"median_A": round(x.median(), 2), "median_B": round(y.median(), 2),
            "A_wins_%": round((x > y).mean() * 100, 1), "B_wins_%": round((y > x).mean() * 100, 1),
            "median_ratio_A_over_B": round((x / y.replace(0, np.nan)).median(), 2),
            "wilcoxon_p": p,
        })
pairs = pd.DataFrame(pairs)
pairs.to_csv(os.path.join(TAB, "same_post_platform_comparison.csv"), index=False)

# posts on all three platforms: which platform got the most impressions / interactions
all3 = wide.dropna(subset=[("impressions", n) for n in NETS] + [("inter_lcs", n) for n in NETS])
win = pd.DataFrame({
    "most_impressions": all3["impressions"][NETS].idxmax(axis=1).value_counts(normalize=True).mul(100).round(1),
    "most_interactions": all3["inter_lcs"][NETS].idxmax(axis=1).value_counts(normalize=True).mul(100).round(1),
    "highest_rate": all3["rate_lcs"][NETS].idxmax(axis=1).value_counts(normalize=True).mul(100).round(1),
}).fillna(0)
win.to_csv(os.path.join(TAB, "same_post_all3_winner_share.csv"))

# by topic: same-post IG vs LinkedIn
both = wide.dropna(subset=[("impressions", "instagram"), ("impressions", "linkedin")]).copy()
bt = pd.DataFrame({
    "topic": gtopic.reindex(both.index),
    "ig_impr": both[("impressions", "instagram")], "li_impr": both[("impressions", "linkedin")],
    "ig_inter": both[("inter_lcs", "instagram")], "li_inter": both[("inter_lcs", "linkedin")],
    "ig_rate": both[("rate_lcs", "instagram")], "li_rate": both[("rate_lcs", "linkedin")],
})
bt["fb_impr"] = wide[("impressions", "facebook")].reindex(bt.index)
bt["fb_inter"] = wide[("inter_lcs", "facebook")].reindex(bt.index)
tt = bt.groupby("topic").agg(matched_posts=("ig_impr", "size"),
                             ig_median_impr=("ig_impr", "median"), li_median_impr=("li_impr", "median"), fb_median_impr=("fb_impr", "median"),
                             ig_median_inter=("ig_inter", "median"), li_median_inter=("li_inter", "median"), fb_median_inter=("fb_inter", "median"),
                             ig_median_rate=("ig_rate", "median"), li_median_rate=("li_rate", "median"))
tt["ig_beats_li_impr_%"] = bt.assign(w=bt.ig_impr > bt.li_impr).groupby("topic").w.mean().mul(100)
tt["ig_beats_li_inter_%"] = bt.assign(w=bt.ig_inter > bt.li_inter).groupby("topic").w.mean().mul(100)
tt = tt.round(1).sort_values("matched_posts", ascending=False)
tt.to_csv(os.path.join(TAB, "same_post_by_topic.csv"))

# full matched list for spot checks
lst = pd.DataFrame({"first_published": gdate, "topic": gtopic, "headline": ghead}).join(
    wide[["impressions", "inter_lcs"]].set_axis([f"{m}_{n}" for m, n in wide[["impressions", "inter_lcs"]].columns], axis=1)).join(
    gfmt.add_prefix("format_"))
lst.sort_values("first_published").to_csv(os.path.join(TAB, "same_post_matched_list.csv"))

# ---- topic x platform (all organic feed posts, not just matched) ----
a = d[d.in_feed_analysis & (d.age >= 14) & d.network.isin(NETS)].copy()
a.loc[a.network.eq("facebook") & a.zero_impressions, "impressions"] = np.nan
a["inter_lcs"] = a[["likes", "comments", "shares"]].sum(axis=1, min_count=1)
a["rate_lcs"] = a.inter_lcs / a.impressions.where(a.impressions > 0) * 100
tp = a[~a.topic.isin(["No caption", "Unclassified"])].pivot_table(index="topic", columns="network",
                                                                    values=["impressions", "inter_lcs", "rate_lcs", "id"],
                                                                    aggfunc={"impressions": "median", "inter_lcs": "median", "rate_lcs": "median", "id": "size"})
tp = tp.rename(columns={"id": "posts", "inter_lcs": "median_interactions", "impressions": "median_impressions", "rate_lcs": "median_rate_%"}, level=0).round(1)
tp.to_csv(os.path.join(TAB, "topic_by_platform.csv"))

# ---- charts ----
C = {"instagram": "#C13584", "facebook": "#1877F2", "linkedin": "#0A66C2"}
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "font.size": 8.5})
fig, ax = plt.subplots(1, 2, figsize=(13, 5), dpi=130)
x, y = both[("impressions", "instagram")], both[("impressions", "linkedin")]
ax[0].scatter(y, x, s=12, alpha=.5, color="#555")
lim = [50, max(x.max(), y.quantile(.99)) * 1.1]
ax[0].plot(lim, lim, "--", color="red", lw=1)
ax[0].set_xscale("log"); ax[0].set_yscale("log"); ax[0].set_xlim(lim); ax[0].set_ylim(lim)
ax[0].set_xlabel("LinkedIn impressions"); ax[0].set_ylabel("Instagram impressions")
ax[0].set_title(f"Same post, Instagram vs LinkedIn (n={len(both)})\nAbove the red line = Instagram did better ({(x > y).mean()*100:.0f}% of posts)")
tops = tt[tt.matched_posts >= 8].sort_values("matched_posts")
yy = np.arange(len(tops)); h = .27
for i, (n, col) in enumerate([("instagram", "ig_median_impr"), ("linkedin", "li_median_impr"), ("facebook", "fb_median_impr")]):
    ax[1].barh(yy + (i - 1) * h, tops[col], h, color=C[n], label=n.title())
ax[1].set_yticks(yy); ax[1].set_yticklabels([f"{t} (n={int(m)})" for t, m in zip(tops.index, tops.matched_posts)])
ax[1].set_xlabel("Median impressions — same posts on each platform"); ax[1].legend()
ax[1].set_title("Same-post performance by topic")
fig.tight_layout(); fig.savefig(os.path.join(CH, "same_post_comparison.png")); plt.close(fig)

pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
print(pairs.to_string(index=False)); print(win); print(tt.to_string()); print(tp.to_string())
print("matched groups:", len(wide), "all3:", len(all3), "ig+li:", len(both))
print("format agreement IG vs LI:", pd.crosstab(gfmt.get("instagram"), gfmt.get("linkedin")))
