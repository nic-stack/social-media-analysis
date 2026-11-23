"""Run the five analyses. Usage: python -I analyze.py <project_dir>"""
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

P = sys.argv[1]
RAW = os.path.join(P, "raw")
OUT = os.path.join(P, "outputs")
TAB = os.path.join(OUT, "tables")
CH = os.path.join(OUT, "charts")
os.makedirs(TAB, exist_ok=True)
os.makedirs(CH, exist_ok=True)


def raw_file(net, kind):
    """Find the single raw export for a network, e.g. *_instagram_*_daily.csv"""
    hits = glob.glob(os.path.join(RAW, f"*_{net}_*_{kind}.csv"))
    assert len(hits) == 1, (net, kind, hits)
    return hits[0]


pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

COLORS = {"instagram": "#C13584", "facebook": "#1877F2", "linkedin": "#0A66C2", "tiktok": "#111111"}
plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False, "font.size": 9})

posts = pd.read_csv(os.path.join(P, "prepared", "posts_prepared.csv"), parse_dates=["published_at"])
EXPORT = pd.Timestamp("2026-11-11")
posts["age_days"] = (EXPORT - posts["published_at"]).dt.days
# feed posts with enough time to accumulate results (>=14 days old at export)
feed = posts[posts.in_feed_analysis & (posts.age_days >= 14)].copy()

# primary outcome per platform
PRIMARY = {
    "instagram": ("reach", "interaction_rate_reach", "Reach"),
    "facebook": ("impressions", "interaction_rate_impr", "Impressions"),
    "linkedin": ("impressions", "interaction_rate_impr", "Impressions"),
}
feed.loc[feed.network.eq("facebook") & feed.zero_impressions, ["impressions", "interaction_rate_impr"]] = np.nan


def summarize(df, by, net):
    vol, rate, _ = PRIMARY[net]
    g = df.groupby(by)
    t = pd.DataFrame({
        "posts": g.size(),
        f"median_{vol}": g[vol].median(),
        "median_interactions": g["interactions"].median(),
        "median_interaction_rate_%": g[rate].median() * 100,
    })
    if net == "linkedin":
        t["median_clicks"] = g["clicks"].median()
    if net == "instagram":
        t["median_saves"] = g["saves"].median()
        t["median_shares"] = g["shares"].median()
    t["small_sample"] = t["posts"] < 10
    return t.round(2)


def kw(df, by, col):
    groups = [g[col].dropna().values for _, g in df.groupby(by) if g[col].notna().sum() >= 5]
    if len(groups) < 2:
        return np.nan
    return stats.kruskal(*groups).pvalue


report = {}

# ============ STEP 1: topics, student/life flags, CTA ============
rows = []
for net in PRIMARY:
    d = feed[feed.network == net]
    vol, rate, _ = PRIMARY[net]
    for dim in ["topic", "student_focused", "campus_life", "cta", "destination", "program_group", "program_area"]:
        t = summarize(d, dim, net)
        t.insert(0, "dimension", dim)
        t.insert(0, "network", net)
        t["kruskal_p_volume"] = kw(d, dim, vol)
        t["kruskal_p_rate"] = kw(d, dim, rate)
        rows.append(t.reset_index().rename(columns={dim: "group"}))
step1 = pd.concat(rows)
step1.to_csv(os.path.join(TAB, "step1_content_performance.csv"), index=False)
report["step1"] = step1

# chart: topic median primary volume & rate by network
topics = [t for t in feed.topic.value_counts().index if t not in ("No caption", "Unclassified")]
fig, axes = plt.subplots(2, 3, figsize=(15, 8.5))
for j, net in enumerate(PRIMARY):
    vol, rate, label = PRIMARY[net]
    t = summarize(feed[feed.network == net], "topic", net).reindex(topics).dropna(subset=["posts"])
    t = t[t.posts >= 5].sort_values(f"median_{vol}")
    for i, (col, xl) in enumerate([(f"median_{vol}", f"Median {label.lower()} per post"), ("median_interaction_rate_%", "Median interaction rate (%)")]):
        ax = axes[i, j]
        ax.barh(t.index, t[col], color=COLORS[net])
        for y, (v, n) in enumerate(zip(t[col], t.posts)):
            ax.text(v, y, f" {v:,.0f}" if i == 0 else f" {v:.1f}%", va="center", fontsize=7)
            ax.text(0, y, f"n={int(n)} ", va="center", ha="right", fontsize=6, color="grey") if False else None
        ax.set_title(f"{net.title()} — {xl}", fontsize=9)
        ax.set_yticks(range(len(t)))
        ax.set_yticklabels([f"{k} (n={int(n)})" for k, n in zip(t.index, t.posts)], fontsize=7)
fig.suptitle("Step 1 — Topic performance by platform (organic feed posts ≥14 days old; topics with ≥5 posts)", fontsize=11)
fig.tight_layout()
fig.savefig(os.path.join(CH, "step1_topic_performance.png"))
plt.close(fig)

# ============ STEP 2: formats ============
rows = []
for net in PRIMARY:
    d = feed[feed.network == net]
    t = summarize(d, "format", net)
    vol, rate, _ = PRIMARY[net]
    t["kruskal_p_volume"] = kw(d, "format", vol)
    t["kruskal_p_rate"] = kw(d, "format", rate)
    t.insert(0, "network", net)
    rows.append(t.reset_index())
step2 = pd.concat(rows)
# stories (IG) separately
st = posts[posts.is_story & posts.network.eq("instagram") & ~posts.incomplete_month].copy()
for c in ["impressions", "reach"]:
    st[c] = pd.to_numeric(st[c], errors="coerce")
story_m = st.groupby("month").agg(stories=("id", "size"), median_story_reach=("reach", "median"), median_story_impr=("impressions", "median"))
step2.to_csv(os.path.join(TAB, "step2_format_performance.csv"), index=False)
story_m.to_csv(os.path.join(TAB, "step2_instagram_stories_monthly.csv"))
report["step2"] = step2

fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
for ax, net in zip(axes, PRIMARY):
    vol, rate, label = PRIMARY[net]
    d = feed[feed.network == net]
    fmts = [f for f in d.format.value_counts().index if (d.format == f).sum() >= 5]
    data = [d.loc[d.format == f, vol].dropna() for f in fmts]
    ax.boxplot(data, showfliers=False, patch_artist=True, boxprops=dict(facecolor=COLORS[net], alpha=.5))
    ax.set_xticks(range(1, len(fmts) + 1))
    ax.set_xticklabels([f"{f}\n(n={len(x)})" for f, x in zip(fmts, data)], fontsize=7)
    ax.set_title(f"{net.title()} — {label.lower()} per post")
fig.suptitle("Step 2 — Format performance (box = middle 50% of posts, line = median; outliers hidden)", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(CH, "step2_format_performance.png"))
plt.close(fig)

# ============ STEP 3: Instagram decline ============
igd = pd.read_csv(raw_file("instagram", "daily"), encoding="utf-8-sig")
igd["date"] = pd.to_datetime(igd["date"], format="%B %d, %Y")
igd["month"] = igd.date.dt.to_period("M").astype(str)
igd = igd[igd.month != "2026-11"]
igm = igd.groupby("month").agg(profile_impressions=("impressions", "sum"), profile_engagement=("engagement", "sum"),
                               profile_views=("profile_views", "sum"), followers_end=("followers", "last"))
igf = posts[posts.in_feed_analysis & posts.network.eq("instagram") & ~posts.incomplete_month]
igm = igm.join(igf.groupby("month").agg(feed_posts=("id", "size"), median_reach_per_feed_post=("reach", "median"),
                                        total_feed_reach=("reach", "sum"), median_interactions=("interactions", "median")))
igm = igm.join(story_m["stories"])
igm.to_csv(os.path.join(TAB, "step3_instagram_monthly.csv"))
# decomposition: Jun-Aug 2026 vs Sep-Oct 2026 (per month)
a = igm.loc[["2026-06", "2026-07", "2026-08"]].mean()
b = igm.loc[["2026-09", "2026-10"]].mean()
decomp = pd.DataFrame({"jun_aug_2026_avg": a, "sep_oct_2026_avg": b, "pct_change": (b / a - 1) * 100}).round(1)
# same months last year
c = igm.loc[["2025-06", "2025-07", "2025-08"]].mean()
d_ = igm.loc[["2025-09", "2025-10"]].mean()
decomp["jun_aug_2025_avg"] = c.round(1)
decomp["sep_oct_2025_avg"] = d_.round(1)
decomp["pct_change_2025"] = ((d_ / c - 1) * 100).round(1)
decomp.to_csv(os.path.join(TAB, "step3_instagram_decline_decomposition.csv"))
report["step3"] = (igm, decomp)

fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
x = range(len(igm))
axes[0].bar(x, igm.profile_impressions / 1e3, color=COLORS["instagram"], alpha=.7)
axes[0].set_ylabel("Profile views/impr.\n(thousands)")
axes[1].bar(x, igm.feed_posts, color="grey", label="Feed posts")
axes[1].plot(x, igm.stories / 5, color="black", marker=".", label="Stories ÷ 5")
axes[1].legend(fontsize=7)
axes[1].set_ylabel("Posts / month")
axes[2].plot(x, igm.median_reach_per_feed_post, color=COLORS["instagram"], marker="o")
axes[2].set_ylabel("Median reach\nper feed post")
axes[2].set_xticks(list(x))
axes[2].set_xticklabels(igm.index, rotation=60, fontsize=7)
fig.suptitle("Step 3 — Instagram: total impressions vs posting volume vs per-post reach (complete months)", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(CH, "step3_instagram_decline.png"))
plt.close(fig)

# ============ STEP 4: day / time ============
def daypart(h):
    return "Morning (<12)" if h < 12 else "Midday (12-14)" if h < 15 else "Afternoon (15-17)" if h < 18 else "Evening (18+)"


feed["daypart"] = feed.hour.map(daypart)
feed["weekday_g"] = feed.weekday.where(~feed.weekday.isin(["Saturday", "Sunday"]), "Weekend")
rows = []
for net in PRIMARY:
    d = feed[feed.network == net]
    vol, rate, _ = PRIMARY[net]
    for dim in ["daypart", "weekday_g"]:
        t = summarize(d, dim, net)
        t["kruskal_p_volume"] = kw(d, dim, vol)
        t["kruskal_p_rate"] = kw(d, dim, rate)
        t.insert(0, "dimension", dim)
        t.insert(0, "network", net)
        rows.append(t.reset_index().rename(columns={dim: "group"}))
step4 = pd.concat(rows)
step4.to_csv(os.path.join(TAB, "step4_day_time_performance.csv"), index=False)
report["step4"] = step4

# IG online followers by hour (audience activity)
igb = pd.read_csv(raw_file("instagram", "daily_breakdowns"), encoding="utf-8-sig")
onl = igb[(igb.dimension == "Hour of day") & (igb.measure == "Online followers")]
onl_h = onl.groupby("bucket")["value"].mean().round(0)
onl_h.to_csv(os.path.join(TAB, "step4_instagram_online_followers_by_hour.csv"))

order_dp = ["Morning (<12)", "Midday (12-14)", "Afternoon (15-17)", "Evening (18+)"]
order_wd = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Weekend"]
fig, axes = plt.subplots(2, 3, figsize=(14, 6.5))
for j, net in enumerate(PRIMARY):
    vol, rate, label = PRIMARY[net]
    for i, (dim, order) in enumerate([("daypart", order_dp), ("weekday_g", order_wd)]):
        t = step4[(step4.network == net) & (step4.dimension == dim)].set_index("group").reindex(order).dropna(subset=["posts"])
        ax = axes[i, j]
        ax.bar(range(len(t)), t[f"median_{vol}"], color=[COLORS[net] if n >= 10 else "lightgrey" for n in t.posts])
        ax.set_xticks(range(len(t)))
        ax.set_xticklabels([f"{g}\nn={int(n)}" for g, n in zip(t.index, t.posts)], fontsize=6.5)
        ax.set_title(f"{net.title()} — median {label.lower()}", fontsize=9)
fig.suptitle("Step 4 — Performance by time of day and weekday (grey bars: fewer than 10 posts)", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(CH, "step4_day_time.png"))
plt.close(fig)

# ============ STEP 5: audience growth ============
growth = []
start = {}  # first-day follower balance
for net in ["facebook", "instagram", "linkedin"]:
    d = pd.read_csv(raw_file(net, "daily"), encoding="utf-8-sig")
    d["date"] = pd.to_datetime(d["date"], format="%B %d, %Y")
    d.loc[d.followers == 0, "followers"] = np.nan  # reporting glitch on the export day
    start[net] = d.sort_values("date").followers.iloc[0]
    d["month"] = d.date.dt.to_period("M").astype(str)
    m = d[d.month != "2026-11"].groupby("month")["followers"].last().to_frame("followers_end")
    m["network"] = net
    growth.append(m)
growth = pd.concat(growth).reset_index()
growth["prev"] = growth.groupby("network")["followers_end"].shift()
growth["prev"] = growth.apply(lambda r: start[r.network] if pd.isna(r.prev) else r.prev, axis=1)
growth["net_new"] = growth.followers_end - growth.prev
growth["growth_rate_%"] = (growth.net_new / growth.prev * 100).round(2)
growth["year"] = growth.month.str[:4]
growth.to_csv(os.path.join(TAB, "step5_follower_growth_monthly.csv"), index=False)
ytd = growth[growth.month.str[5:7].astype(int) <= 10].groupby(["network", "year"]).agg(net_new=("net_new", "sum"), avg_monthly_rate=("growth_rate_%", "mean")).round(2)
ytd.to_csv(os.path.join(TAB, "step5_growth_jan_oct_yoy.csv"))
report["step5"] = (growth, ytd)

# domestic share trend (snapshot country = United States)
dom = []
for net in ["facebook", "instagram"]:
    s = pd.read_csv(raw_file(net, "lifetime_snapshots"), encoding="utf-8-sig")
    s = s[(s.dimension == "Country") & (s.measure == "Followers") & (s.measure_total > 0)]
    s["snapshot_date"] = pd.to_datetime(s.snapshot_date, format="%B %d, %Y")
    us = s[s.bucket == "United States"].groupby("snapshot_date").apply(lambda g: g.value.sum() / g.measure_total.iloc[0] * 100, include_groups=False)
    us = us.groupby(us.index.to_period("M")).last().rename(net)
    dom.append(us)
dom = pd.concat(dom, axis=1).round(1)
dom.index = dom.index.astype(str)
dom.to_csv(os.path.join(TAB, "step5_us_follower_share_monthly.csv"))
report["dom"] = dom

fig, axes = plt.subplots(1, 2, figsize=(14, 4))
for net in start:
    g = growth[growth.network == net]
    axes[0].plot(g.month, g["growth_rate_%"], marker=".", color=COLORS[net], label=net.title())
axes[0].set_title("Monthly follower growth rate (%)")
axes[0].legend()
axes[0].tick_params(axis="x", rotation=70, labelsize=6.5)
for net in dom:
    axes[1].plot(dom.index, dom[net], marker=".", color=COLORS[net], label=net.title())
axes[1].set_title("Share of followers in the United States (%)")
axes[1].legend()
axes[1].tick_params(axis="x", rotation=70, labelsize=6.5)
fig.suptitle("Step 5 — Audience growth (complete months; Nov 2026 excluded)", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(CH, "step5_growth.png"))
plt.close(fig)

# ============ console summary ============
cols = lambda t: [c for c in t.columns if c not in ("kruskal_p_volume", "kruskal_p_rate", "small_sample")]
print("FEED POSTS ANALYZED:", feed.network.value_counts().to_dict())
for net in PRIMARY:
    s = step1[step1.network == net]
    for dim in ["topic", "student_focused", "campus_life", "cta", "program_group"]:
        t = s[s.dimension == dim]
        print(f"\n--- STEP1 {net} by {dim}  (KW p vol={t.kruskal_p_volume.iloc[0]:.3g}, rate={t.kruskal_p_rate.iloc[0]:.3g})")
        print(t[[c for c in cols(t) if c not in ("network", "dimension")]].sort_values("posts", ascending=False).to_string(index=False))
print("\n--- STEP2")
print(step2.to_string(index=False))
print("\n--- STEP3 monthly")
print(igm.round(0).to_string())
print(decomp.to_string())
print("\n--- STEP4")
print(step4.to_string(index=False))
print("IG online followers by hour:", onl_h.to_dict())
print("\n--- STEP5")
print(ytd.to_string())
print(growth.pivot(index="month", columns="network", values="net_new").to_string())
print(dom.iloc[[0, 6, 12, 18, -1]].to_string())
