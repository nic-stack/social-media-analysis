"""Platform overview. Usage: python -I platform_overview.py <project_dir>"""
import glob, os, sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd, numpy as np
P = sys.argv[1]
po = pd.read_csv(os.path.join(P, "prepared", "posts_prepared.csv"), parse_dates=["published_at"])
po["age"] = (pd.Timestamp("2026-11-11") - po.published_at).dt.days
f = po[po.in_feed_analysis & (po.age >= 14)].copy()
f.loc[f.network.eq("facebook") & f.zero_impressions, ["impressions", "interaction_rate_impr"]] = np.nan
tt = po[po.network.eq("tiktok")]
f = pd.concat([f, tt])
months = 22  # complete months Jan 2025-Oct 2026
g = f.groupby("network")
ov = pd.DataFrame({
    "feed_posts": g.size(),
    "posts_per_month": (g.size() / months).round(1),
    "median_impressions": g.impressions.median(),
    "median_reach": g.reach.median(),
    "median_likes": g.likes.median(),
    "median_comments": g.comments.median(),
    "median_shares": g.shares.median(),
    "median_interactions": g.interactions.median(),
    "median_interaction_rate_impr_%": (g.interaction_rate_impr.median() * 100).round(2),
    "median_clicks": g.clicks.median(),
    "p90_impressions": g.impressions.quantile(.9),
})
ov.loc["tiktok", "posts_per_month"] = np.nan
st = po[po.is_story & ~po.incomplete_month].groupby("network").size()
ov["stories_total"] = st
fol = {}
for n in ov.index:
    fd = pd.read_csv(glob.glob(os.path.join(P, "raw", f"*_{n}_*_daily.csv"))[0], encoding="utf-8-sig")
    fd["date"] = pd.to_datetime(fd["date"], format="%B %d, %Y")
    fd = fd[fd.date < "2026-11-01"].sort_values("date")
    fol[n] = (fd.followers.iloc[0], fd.followers.iloc[-1])
ov["followers_jan2025"] = [fol[n][0] for n in ov.index]
ov["followers_oct2026"] = [fol[n][1] for n in ov.index]
ov["follower_growth_%"] = [round((b / a - 1) * 100, 1) if a else np.nan for a, b in (fol[n] for n in ov.index)]
ov["median_impr_per_100_followers"] = (ov.median_impressions / ov.followers_oct2026 * 100).round(1)
ov.to_csv(os.path.join(P, "outputs", "tables", "platform_overview.csv"))
# monthly median impressions per platform (feed)
f2 = po[po.in_feed_analysis & ~po.incomplete_month & po.network.ne("tiktok")].copy()
f2.loc[f2.network.eq("facebook") & f2.zero_impressions, "impressions"] = np.nan
mm = f2.groupby(["month", "network"]).agg(posts=("id", "size"), median_impr=("impressions", "median"), median_inter=("interactions", "median")).unstack()
mm.to_csv(os.path.join(P, "outputs", "tables", "platform_monthly.csv"))
# by year
f2["year"] = f2.month.str[:4]
yy = f2[f2.month.str[5:7].astype(int) <= 10].groupby(["network", "year"]).agg(posts=("id", "size"), median_impr=("impressions", "median"), median_interactions=("interactions", "median"), median_rate=("interaction_rate_impr", "median"))
yy["median_rate"] = (yy.median_rate * 100).round(2)
yy.to_csv(os.path.join(P, "outputs", "tables", "platform_yoy_jan_oct.csv"))
print(ov.T.to_string()); print(yy.to_string())
C = {"instagram": "#C13584", "facebook": "#1877F2", "linkedin": "#0A66C2"}
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "font.size": 9})
fig, ax = plt.subplots(1, 3, figsize=(15, 4), dpi=130)
nets = ["instagram", "facebook", "linkedin"]
for a, col, t in [(ax[0], "median_impressions", "Median impressions per feed post"), (ax[1], "median_interactions", "Median interactions per feed post")]:
    v = ov.loc[nets, col]; a.bar([n.title() for n in nets], v, color=[C[n] for n in nets])
    for i, x in enumerate(v): a.text(i, x, f"{x:,.0f}", ha="center", va="bottom")
    a.set_title(t)
for n in nets:
    ax[2].plot(mm.index, mm[("median_impr", n)], marker=".", color=C[n], label=n.title())
ax[2].set_title("Median impressions per feed post, by month"); ax[2].legend(); ax[2].tick_params(axis="x", rotation=70, labelsize=6.5)
fig.suptitle("Platform comparison — organic feed posts (metric definitions differ by platform; compare with care)", fontsize=10)
fig.tight_layout(); fig.savefig(os.path.join(P, "outputs", "charts", "platform_comparison.png"))
