from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from ..config.config import MIN_DURATION_SECONDS
from ..models import YouTubeVideo

Decision = Literal["analyze", "skip"]

DEFAULT_CATEGORY_QUOTA_RATIOS = {
    "politics_geopolitics": 0.45,
    "macro_market": 0.30,
    "business_tech": 0.20,
    "crypto": 0.05,
}


@dataclass(frozen=True)
class VideoValueDecision:
    video: YouTubeVideo
    score: int
    decision: Decision
    reason: str
    category_hint: str


MACRO_TERMS = {
    "fed",
    "fomc",
    "rate",
    "rates",
    "inflation",
    "cpi",
    "jobs",
    "unemployment",
    "recession",
    "dollar",
    "treasury",
    "bond",
    "oil",
    "tariff",
    "gdp",
    "liquidity",
}

GEOPOLITICS_TERMS = {
    "iran",
    "israel",
    "ukraine",
    "russia",
    "china",
    "nato",
    "war",
    "ceasefire",
    "sanctions",
    "election",
    "trump",
    "policy",
    "congress",
    "senate",
    "white house",
}

BUSINESS_TECH_TERMS = {
    "nvidia",
    "tesla",
    "spacex",
    "openai",
    "ai",
    "ipo",
    "earnings",
    "stock",
    "market",
    "markets",
    "semiconductor",
    "chips",
}

CRYPTO_TERMS = {
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "crypto",
    "solana",
    "sol",
    "xrp",
    "stablecoin",
    "defi",
    "etf",
}

# Channel priority is maintained by operators in youtube_crypto_channels.  A high
# priority channel is treated as a KOL only when it is discussing a current event,
# rather than receiving a blanket boost for every upload.
KOL_HOT_EVENT_MIN_CHANNEL_PRIORITY = 10
KOL_HOT_EVENT_TERMS = MACRO_TERMS | GEOPOLITICS_TERMS

SPORTS_BETTING_TERMS = {
    "mlb betting",
    "nba betting",
    "nfl betting",
    "sportsbook",
    "betting picks",
    "best bets",
    "wager",
}

LOW_VALUE_TERMS = {
    "celebrity gossip",
    "funny moments",
    "reaction compilation",
    "watch now",
    "live stream",
}

NEWS_WIRE_CHANNEL_TERMS = {
    "bloomberg television",
    "bloomberg podcasts",
    "times news",
    "the hill",
    "cnbc television",
}

MACRO_CHANNEL_TERMS = {"real vision", "wealthion", "tastylive", "all-in"}
GEOPOLITICS_CHANNEL_TERMS = {"csis", "zeihan", "breaking points"}
CRYPTO_CHANNEL_TERMS = {
    "coin bureau",
    "bankless",
    "unchained",
    "altcoin daily",
    "benjamin cowen",
}
SPORTS_CHANNEL_TERMS = {"wagertalk", "tifo football"}


def _text_for(video: YouTubeVideo, channel_title: str | None) -> str:
    pieces: list[str] = [video.title or "", video.description or "", channel_title or ""]
    if video.tags:
        pieces.extend(video.tags)
    return " ".join(pieces).lower()


def _count_matches(text: str, terms: Iterable[str]) -> int:
    return sum(1 for term in terms if term in text)


def _top_category(text: str) -> tuple[str, int]:
    category_scores = {
        "macro_market": _count_matches(text, MACRO_TERMS),
        "politics_geopolitics": _count_matches(text, GEOPOLITICS_TERMS),
        "business_tech": _count_matches(text, BUSINESS_TECH_TERMS),
        "crypto": _count_matches(text, CRYPTO_TERMS),
    }
    return max(category_scores.items(), key=lambda item: item[1])


def score_video_for_analysis(
    video: YouTubeVideo,
    *,
    channel_title: str | None = None,
) -> VideoValueDecision:
    """Score whether a video deserves paid transcription and claim extraction."""
    channel_title = channel_title or getattr(video, "channel_title", None)
    duration = video.duration_seconds or 0
    if duration < MIN_DURATION_SECONDS:
        return VideoValueDecision(video, 0, "skip", "short_duration", "short")

    text = _text_for(video, channel_title)
    if _count_matches(text, SPORTS_BETTING_TERMS) or _count_matches(
        channel_title.lower() if channel_title else "", SPORTS_CHANNEL_TERMS
    ):
        return VideoValueDecision(video, 0, "skip", "sports_betting_noise", "sports")

    if _count_matches(text, LOW_VALUE_TERMS) and not (
        _count_matches(text, MACRO_TERMS)
        or _count_matches(text, GEOPOLITICS_TERMS)
        or _count_matches(text, BUSINESS_TECH_TERMS)
    ):
        return VideoValueDecision(video, 10, "skip", "low_information_noise", "other")

    category, hit_count = _top_category(text)
    score = 0
    reasons: list[str] = []
    channel_priority = getattr(video, "channel_priority", None) or 0

    if category == "macro_market" and hit_count:
        score = 76
        reasons.append("macro_market")
    elif category == "politics_geopolitics" and hit_count:
        score = 72
        reasons.append("politics_geopolitics")
    elif category == "business_tech" and hit_count:
        score = 62
        reasons.append("business_tech")
    elif category == "crypto" and hit_count:
        score = 38
        reasons.append("crypto_lower_priority")
    else:
        score = 20
        reasons.append("weak_topic_match")

    if _count_matches(text, MACRO_CHANNEL_TERMS):
        score += 10
        reasons.append("macro_channel")
    if _count_matches(text, GEOPOLITICS_CHANNEL_TERMS):
        score += 10
        reasons.append("geopolitics_channel")
    if _count_matches(text, CRYPTO_CHANNEL_TERMS):
        score += 4
        reasons.append("crypto_channel")
    if _count_matches(text, NEWS_WIRE_CHANNEL_TERMS):
        score -= 18
        reasons.append("news_wire_channel")

    hot_event_hits = _count_matches(text, KOL_HOT_EVENT_TERMS)
    if channel_priority >= KOL_HOT_EVENT_MIN_CHANNEL_PRIORITY and hot_event_hits:
        score += min(24, 12 + channel_priority)
        reasons.append("high_priority_kol_hot_event")

    # More direct event/market terms mean a better chance of matching PredX markets.
    extra_hits = (
        _count_matches(text, MACRO_TERMS)
        + _count_matches(text, GEOPOLITICS_TERMS)
        + _count_matches(text, BUSINESS_TECH_TERMS)
        + _count_matches(text, CRYPTO_TERMS)
    )
    score += min(extra_hits * 2, 16)
    score = max(0, min(score, 100))

    decision: Decision = "analyze" if score >= 50 else "skip"
    reason = ",".join(reasons)
    return VideoValueDecision(video, score, decision, reason, category)


def select_videos_for_analysis(
    videos: Sequence[YouTubeVideo],
    *,
    limit: int,
) -> list[VideoValueDecision]:
    decisions = [score_video_for_analysis(video) for video in videos]
    selected = [item for item in decisions if item.decision == "analyze"]
    sorted_selected = sorted(selected, key=lambda item: item.score, reverse=True)
    if limit < 10:
        return sorted_selected[:limit]

    quotas = _category_quotas(limit)
    by_category: dict[str, list[VideoValueDecision]] = {
        category: [] for category in quotas
    }
    for item in sorted_selected:
        if item.category_hint in by_category:
            by_category[item.category_hint].append(item)

    chosen: list[VideoValueDecision] = []
    chosen_ids: set[str] = set()
    for category, quota in quotas.items():
        for item in by_category.get(category, [])[:quota]:
            chosen.append(item)
            chosen_ids.add(item.video.video_id)

    if len(chosen) < limit:
        for item in sorted_selected:
            if item.video.video_id in chosen_ids:
                continue
            chosen.append(item)
            chosen_ids.add(item.video.video_id)
            if len(chosen) >= limit:
                break

    return sorted(chosen, key=lambda item: item.score, reverse=True)[:limit]


def _category_quotas(limit: int) -> dict[str, int]:
    quotas = {
        category: int(limit * ratio)
        for category, ratio in DEFAULT_CATEGORY_QUOTA_RATIOS.items()
    }
    assigned = sum(quotas.values())
    # Assign rounding leftovers to the highest-priority categories in order.
    for category in DEFAULT_CATEGORY_QUOTA_RATIOS:
        if assigned >= limit:
            break
        quotas[category] += 1
        assigned += 1
    return quotas
