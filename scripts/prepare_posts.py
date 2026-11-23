"""Build a prepared post table with derived topic / CTA / destination fields.

Usage: python -I prepare_posts.py <raw_post_csv> <out_csv> <org_config.json>
Organization-specific terms (names, hashtags, programs, domains) live in the config file.
All derived fields are analysis additions (keyword rules), not source facts.
"""
import json
import re
import sys
import unicodedata

import numpy as np
import pandas as pd

src, out = sys.argv[1], sys.argv[2]
CFG = json.load(open(sys.argv[3], encoding="utf-8"))


def org(key):
    """Optional extra regex alternatives from the config (never an empty alternative)."""
    return "|" + CFG[key] if CFG.get(key) else ""

df = pd.read_csv(src, encoding="utf-8-sig", low_memory=False)

df["published_at"] = pd.to_datetime(df["date"] + " " + df["time"], format="%B %d, %Y %I:%M %p")
df["pub_date"] = df["published_at"].dt.date
df["month"] = df["published_at"].dt.to_period("M").astype(str)
df["weekday"] = df["published_at"].dt.day_name()
df["hour"] = df["published_at"].dt.hour

typ = df["type"].fillna("")
df["is_story"] = typ.str.contains("Story")
df["is_dark"] = df["dark"].astype(str).str.lower().eq("true")
df["format"] = np.select(
    [df["is_story"], typ.isin(["Reel", "Video"]), typ.eq("Carousel") | typ.eq("Images"), typ.eq("Image"), typ.eq("Article")],
    ["Story", "Video/Reel", "Carousel/Multi-image", "Single image", "Link/Article"],
    default="Unknown/Generic",
)
# Population used for organic feed-post analysis
df["in_feed_analysis"] = ~df["is_story"] & ~df["is_dark"] & df["network"].ne("tiktok")
df["incomplete_month"] = df["month"].eq("2026-11")

# ---- caption normalisation (fancy unicode bold -> plain) ----
def norm(s):
    if not isinstance(s, str):
        return ""
    return unicodedata.normalize("NFKC", s)

text = df["message"].map(norm)
df["caption_blank"] = text.str.strip().eq("")
headline = text.str.split("\n").str[0].str.strip()
low = text.str.lower()
hlow = headline.str.lower()

def has(series, pat):
    return series.str.contains(pat, regex=True, na=False)

# ---- primary topic: ordered rules; first match wins ----
rules = [
    ("Career & networking events roundup", "high",
     has(low, r"check out these (?:exciting )?(?:upcoming )?.{0,45}(?:networking|professional development) events" + org("event_roundup_terms"))),
    ("Curated reading list", "high", has(low, r"what we(?:'|’)re reading")),
    ("Program & admissions promo", "high",
     has(low, r"no gre|info(?:rmation)? session|open house|apply (?:now|today)|now accepting|earn your|with va benefits" + org("promo_terms"))
     | has(hlow, r"^\W*(?:☑️|✔️|✅)|top \d+ (?:private )?university|u\.?s\.? news|best value|^(?:☑️|✔️)?\s*m\.s\. in|new (?:transfer )?(?:b\.s\.|m\.s\.|m\.a\.|ph\.d)|accreditation|pass rate")),
    ("Graduation & ceremonies", "high",
     has(hlow, r"commencement|graduat(?:es|ion)\b|just graduated|class of 20\d\d|white coat|pinning|congratulations.{0,40}(?:class|grads|graduates)|newest alumni" + org("graduation_terms"))),
    ("Orientation & welcome", "high", has(hlow, r"orientation|welcome our newest|welcome, new" + org("welcome_terms"))),
    ("Career & networking events roundup", "medium", has(hlow, r"networking|career (?:fair|event|support)") & ~has(hlow, r"\\bstudents?\\b|\\balum|\\bgrads?\\b")),
    ("Student & alumni stories", "high",
     has(hlow, r"\bstudents?\b|\balum|\bgrads?\b|\bgraduate students?|ph\.?d\.? candidate|^meet [a-z]+|'2\d\b|’2\d\b|scholar\b")),
    ("Event promotion & recaps", "high",
     has(hlow, r"join us|rsvp|register|tomorrow|symposium|conference|workshop|guest talk|book talk|panel|webinar|forum|hackathon|host(?:s|ed|ing)?\b|showcase|visit(?:ing|s)?\b|keynote|summit|event")),
    ("Campus life & culture", "high",
     has(hlow, r"happy |holiday|valentine|holi\b|hanukkah|chanukah|purim|thanksgiving|new year|summer|spring in|fall 20|semester|week \d|basketball|behind the scenes|film roll|pov:" + org("culture_headline_terms"))
     | has(low, CFG["campus_life_hashtag"])),
    ("Research & faculty expertise", "high",
     has(hlow, r"professor|faculty|\bdr\.|dean|director|study|studies|research|scientist|findings|paper|for forbes|interview|physicist|educator|award|\bai\b|system|model|tool|breakthrough|could|may |reveals?|explores?|uncover|detect|smarter|new ")),
    ("Student & alumni stories", "medium", has(low, r"\b(?:student|alum(?:na|nus|ni)?|graduate) (?:of|in|at)\b|\bstudents?\b")),
    ("Research & faculty expertise", "medium", has(low, r"research|study|professor|faculty")),
    ("Campus life & culture", "low", text.str.len().lt(200)),
]
topic = pd.Series("Unclassified", index=df.index)
conf = pd.Series("none", index=df.index)
assigned = pd.Series(False, index=df.index)
for name, c, mask in rules:
    m = mask & ~assigned
    topic[m] = name
    conf[m] = c
    assigned |= m
topic[df["caption_blank"]] = "No caption"
conf[df["caption_blank"]] = "none"
df["topic"] = topic
df["topic_confidence"] = conf

# ---- flags (independent of primary topic) ----
df["student_focused"] = ~df["caption_blank"] & (
    df["topic"].isin(["Student & alumni stories", "Graduation & ceremonies", "Orientation & welcome"])
    | has(hlow, r"\bstudents?\b|\balum|\bgrads?\b|class of 20|ph\.?d\.? candidate|internship")
)
df["campus_life"] = ~df["caption_blank"] & (
    df["topic"].eq("Campus life & culture") | has(low, r"behind the scenes" + org("campus_life_terms"))
)

# ---- program area ----
programs = [(p["name"], p["pattern"]) for p in CFG["programs"]]
prog = pd.Series("General / multiple", index=df.index)
found = pd.Series(False, index=df.index)
for name, pat in programs:
    m = (has(hlow, pat) | (has(low, pat) & ~df["topic"].isin(["Career & networking events roundup", "Curated reading list"]) & False)) & ~found
    prog[m] = name
    found |= m
# fallback: first 400 chars of body, excluding roundup/reading-list posts
body = low.str[:400]
skip = df["topic"].isin(["Career & networking events roundup", "Curated reading list"])
for name, pat in programs:
    m = has(body, pat) & ~found & ~skip
    prog[m] = name
    found |= m
prog[df["caption_blank"]] = "Unknown"
df["program_area"] = prog
area = {p["name"]: p["area"] for p in CFG["programs"]}
df["program_group"] = df["program_area"].map(lambda p: area.get(p, p))

# ---- links / destinations / CTA ----
urls = text.str.findall(r"https?://[^\s)\]]+")
df["link_count"] = urls.str.len()
domains = urls.map(lambda us: [re.sub(r"^www\.", "", re.match(r"https?://([^/]+)", u).group(1).lower()) for u in us])

def dest(ds):
    if not ds:
        return "No link"
    ds = set(ds)
    if ds & {"luma.com", "lu.ma", "eventbrite.com", "meetup.com", "events.zoom.us", *CFG["event_domains"]}:
        return "Event registration"
    if ds & {"forms.cloud.microsoft", "forms.office.com"}:
        return "Form"
    if CFG["org_domain"] in ds:
        return "Organization website"
    if ds & {"bit.ly", "vist.ly", "lnkd.in"}:
        return "Shortened link (unknown)"
    return "External site"

df["destination"] = domains.map(dest)

cta_rules = [
    ("Apply / enroll", r"apply|enroll|admission|info(rmation)? session|open house|learn more about (the|our) program"),
    ("Register / RSVP", r"register|rsvp|sign up|join us|save your spot|reserve"),
    ("Read more", r"read (more|the full)|full story|learn more|link in bio|details:"),
    ("Engage (comment/tag/share)", r"comment|tag a|share your|tell us|drop a"),
]
cta = pd.Series("None", index=df.index)
got = pd.Series(False, index=df.index)
for name, pat in cta_rules:
    m = has(low, pat) & ~got
    cta[m] = name
    got |= m
cta[(cta == "None") & df["link_count"].gt(0)] = "Link only (no explicit ask)"
cta[df["caption_blank"]] = "Unknown"
df["cta"] = cta

df["hashtag_count"] = text.str.count(r"#\w+")
df["caption_length"] = text.str.len()
df["headline"] = headline.str[:140]

# ---- numeric metrics + derived common interaction measure ----
for c in ["impressions", "reach", "likes", "comments", "shares", "saves", "clicks", "engagement", "engagement_rate_by_impressions"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["interactions"] = df[["likes", "comments", "shares"]].sum(axis=1, min_count=1)
ig = df["network"].eq("instagram")
df.loc[ig, "interactions"] = df.loc[ig, ["likes", "comments", "shares", "saves"]].sum(axis=1, min_count=1)
imp = df["impressions"].where(df["impressions"] > 0)
df["interaction_rate_impr"] = df["interactions"] / imp
df["interaction_rate_reach"] = df["interactions"] / df["reach"].where(df["reach"] > 0)
df["zero_impressions"] = df["impressions"].fillna(0).eq(0)

keep = ["id", "publication_group_id", "network", "type", "format", "published_at", "pub_date", "month", "weekday", "hour",
        "is_story", "is_dark", "in_feed_analysis", "incomplete_month", "caption_blank", "headline",
        "topic", "topic_confidence", "student_focused", "campus_life", "program_area", "program_group",
        "cta", "destination", "link_count", "hashtag_count", "caption_length",
        "impressions", "reach", "likes", "comments", "shares", "saves", "clicks", "engagement",
        "engagement_rate_by_impressions", "interactions", "interaction_rate_impr", "interaction_rate_reach",
        "zero_impressions", "published_link", "message"]
df[keep].to_csv(out, index=False)

f = df[df.in_feed_analysis]
print("feed posts in analysis:", len(f))
print(pd.crosstab(f.topic, f.network, margins=True))
print(f.topic_confidence.value_counts().to_dict())
print("student_focused", f.student_focused.mean().round(3), "campus_life", f.campus_life.mean().round(3))
print(f.cta.value_counts().to_dict())
print(f.destination.value_counts().to_dict())
print(f.program_area.value_counts().to_dict())
print(f.format.value_counts().to_dict())
