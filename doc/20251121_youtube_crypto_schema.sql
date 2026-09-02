-- YouTube Crypto Agent Schema
-- Migration: 20251121_youtube_crypto_schema
-- Description: Core tables for monitoring YouTube crypto channels and storing LLM analysis results

-- =====================================================
-- 1. Channel Table
-- =====================================================
-- Stores monitored YouTube channels and polling state
CREATE TABLE IF NOT EXISTS youtube_crypto_channels (
    -- Primary key
    channel_id TEXT PRIMARY KEY,              -- YouTube channel ID

    -- Basic info
    handle TEXT NOT NULL,                     -- @handle (required, used to resolve channel ID)
    title TEXT NOT NULL,
    description TEXT,

    -- Monitoring status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    priority SMALLINT DEFAULT 0,              -- Higher value = higher priority

    -- Channel stats (snapshot)
    subscriber_count BIGINT,
    channel_image TEXT,                      -- YouTube-hosted avatar URL

    -- Polling state
    last_checked_at TIMESTAMPTZ,
    last_video_published_at TIMESTAMPTZ,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for channel table
CREATE INDEX IF NOT EXISTS idx_yc_channels_active
    ON youtube_crypto_channels(is_active)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_yc_channels_priority
    ON youtube_crypto_channels(priority DESC);

-- =====================================================
-- 2. Video Table
-- =====================================================
-- Tracks videos discovered from monitored channels and their analysis state
CREATE TABLE IF NOT EXISTS youtube_crypto_videos (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- Identifiers
    video_id TEXT NOT NULL UNIQUE,            -- YouTube video ID
    channel_id TEXT NOT NULL,                 -- YouTube channel ID (no FK constraint)

    -- Basic info
    title TEXT NOT NULL,
    description TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    thumbnail_url TEXT,

    -- Stats (snapshot when fetched)
    duration_seconds INTEGER,
    view_count BIGINT,
    like_count BIGINT,
    comment_count BIGINT,
    tags TEXT[],

    -- Analysis state
    analysis_status TEXT NOT NULL DEFAULT 'pending',
    last_analysis_at TIMESTAMPTZ,
    last_analysis_version TEXT,

    -- Raw YouTube metadata
    raw_metadata JSONB,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for video table
CREATE INDEX IF NOT EXISTS idx_yc_videos_channel_published
    ON youtube_crypto_videos(channel_id, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_yc_videos_status
    ON youtube_crypto_videos(analysis_status);

CREATE INDEX IF NOT EXISTS idx_yc_videos_published_at
    ON youtube_crypto_videos(published_at DESC);

-- =====================================================
-- 3. Video Analysis Table
-- =====================================================
-- Stores structured LLM analysis results for each video

CREATE TABLE IF NOT EXISTS youtube_crypto_video_analyses (
    id BIGSERIAL PRIMARY KEY,

    -- Relationship to video (logical, no FK constraint)
    video_id TEXT NOT NULL,

    -- Versioning and model info
    analysis_version TEXT NOT NULL,           -- e.g. 'v1_gemini3pro_202503'
    model_name TEXT NOT NULL,                 -- e.g. 'gemini-3.0-pro'

    -- Core outputs (three levels of summary)
    summary_brief TEXT NOT NULL,              -- Very short TL;DR summary
    summary_detailed TEXT,                    -- More detailed explanation
    summary_full TEXT,                        -- Most detailed content description
    transcript TEXT,                          -- Verbatim transcript in the video's original language (Gemini output)
    sentiment TEXT,                           -- 'bullish' | 'bearish' | 'neutral' (free text)
    conviction_score SMALLINT,                -- 0–100, how strong the thesis is
    risk_score SMALLINT,                      -- 0–100, risk evaluation

    -- Structured tags
    key_tokens TEXT[],                        -- Mentioned token symbols
    key_narratives TEXT[],                    -- Narrative tags, e.g. 'ETF', 'L2'

    -- Token usage metrics from LLM call
    prompt_token_count INTEGER,               -- Tokens in prompt (if provided by API)
    candidates_token_count INTEGER,           -- Tokens in candidates / output
    total_token_count INTEGER,                -- Total tokens (prompt + output)
    cached_content_token_count INTEGER,       -- Tokens served from cache (if any)
    elapsed_seconds DOUBLE PRECISION,         -- Wall-clock time for the LLM call

    -- Raw LLM output
    raw_response JSONB,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for analysis table
CREATE INDEX IF NOT EXISTS idx_yc_analysis_video
    ON youtube_crypto_video_analyses(video_id);

CREATE INDEX IF NOT EXISTS idx_yc_analysis_version
    ON youtube_crypto_video_analyses(analysis_version);

CREATE INDEX IF NOT EXISTS idx_yc_analysis_tokens
    ON youtube_crypto_video_analyses
    USING GIN (key_tokens);

CREATE INDEX IF NOT EXISTS idx_yc_analysis_narratives
    ON youtube_crypto_video_analyses
    USING GIN (key_narratives);

-- =====================================================
-- 4. Optional: Daily Stats Snapshot (for future use)
-- =====================================================
-- Not required for initial implementation; included here as a placeholder.
-- Uncomment if you decide to track view/like/comment evolution over time.

-- CREATE TABLE IF NOT EXISTS youtube_crypto_video_daily_stats (
--     video_id TEXT NOT NULL,
--     stat_date DATE NOT NULL,
--     view_count BIGINT,
--     like_count BIGINT,
--     comment_count BIGINT,
--     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--     PRIMARY KEY (video_id, stat_date)
-- );

-- COMMENT ON TABLE youtube_crypto_channels IS 'Monitored YouTube crypto channels';
-- COMMENT ON TABLE youtube_crypto_videos IS 'YouTube videos discovered from monitored channels';
-- COMMENT ON TABLE youtube_crypto_video_analyses IS 'Structured Gemini analysis results for YouTube crypto videos';


INSERT INTO "youtube_crypto_channels" ("channel_id", "handle", "title", "description", "is_active", "priority", "last_checked_at", "last_video_published_at", "created_at", "updated_at", "subscriber_count") VALUES
('UCAl9Ld79qaZxp9JzEOwd3aA', '@Bankless', 'Bankless', '深度/技术：前沿叙事与机构视角，深耕以太坊生态及AI代理与DeFi结合赛道。', 't', 4, '2025-12-19 07:43:31.870789+00', '2025-12-18 11:30:20+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:27.006455+00', 277000),
('UCbLhGKVY-bJPcawebgtNfbw', '@AltcoinDaily', 'Altcoin Daily', '新闻/访谈：每日新闻聚合，高效梳理全网资讯，频繁采访行业大佬。', 't', 3, '2025-12-19 07:43:31.870789+00', '2025-12-18 23:57:13+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:30.17447+00', 1660000),
('UCc4Rz_T9Sb1w5rqqo9pL1Og', '@TheMoon', 'The Moon', '交易/TA：激进技术分析，主要针对衍生品交易者，风格极具煽动性。', 't', 12, '2025-12-19 07:43:31.870789+00', '2025-12-19 04:34:23+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:03.156576+00', 657000),
('UCCatR7nWbYrkVXdxXb4cGXw', '@DataDash', 'DataDash', '宏观/逆向：逆向思维宏观，专注于宏观经济数据与加密市场的相关性。', 't', 19, '2025-12-19 07:47:38.01953+00', '2025-12-18 16:15:03+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:47:42.759227+00', 511000),
('UCcrEA_xd9Ldf1C8DIJYdyyA', '@VirtualBacon', 'VirtualBacon', '交易/策略：实战交易策略，将宏观叙事转化为具体的交易计划和买入逻辑。', 't', 9, '2025-12-19 07:43:31.870789+00', '2025-12-10 22:17:49+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:14.211829+00', 963000),
('UCGXWKlq1Oxr3ddEtmKhAkPg', '@RealVisionFinance', 'Real Vision', '宏观/战略：宏观经济罗盘，连接传统金融与加密市场，提供全球流动性周期分析。', 't', 6, '2025-12-19 07:43:31.870789+00', '2025-12-18 14:15:12+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:22.384887+00', 88100),
('UCHop-jpf-huVT1IYw79ymPw', '@ChicoCrypto', 'Chico Crypto', 'Alpha/揭秘：链上侦探，擅长挖掘早期未发币项目和链上异动，经常揭露VC动向。', 't', 16, '2025-12-19 07:43:31.870789+00', NULL, '2025-11-24 02:18:42.073657+00', '2025-12-19 07:43:45.359854+00', 310000),
('UCI7M65p3A-D3P4v5qW8POxQ', '@CryptosRUs', 'CryptosRUs', '社区/心理：HODL大本营，擅长在市场恐慌时通过基本面分析为持币者充值信仰。', 't', 13, '2025-12-19 07:43:31.870789+00', '2025-12-18 15:17:07+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:43:58.562023+00', 812000),
('UCjemQfjaXAzA-95RKoy9n_g', '@discovercrypto_', 'Discover Crypto', '综合/娱乐：综合媒体网络，原BitBoy Crypto，内容覆盖新闻、纪录片及Meme币分析。', 't', 10, '2025-12-19 07:43:31.870789+00', '2025-12-19 00:05:27+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:12.417547+00', 1400000),
('UCKQvGU-qtjEthINeViNbn6A', '@AlexBeckersChannel', 'Alex Becker', '叙事/游戏：风格激进，专注于Web3游戏和高风险山寨币，能引发板块短期爆发。', 't', 5, '2025-12-19 07:43:31.870789+00', NULL, '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:23.919078+00', 1600000),
('UCl2oCaw8hdR_kbqyqd2klIA', '@TheCryptoLark', 'Lark Davis', '财富/空投：财富自由指南，侧重于财富积累策略、空投教程及低市值山寨币挖掘。', 't', 15, '2025-12-19 07:43:31.870789+00', '2025-12-18 23:01:26+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:43:50.486611+00', 639000),
('UClgJyzwGs-GyaNxUHcLZrkg', '@InvestAnswers', 'InvestAnswers', '数据/生态：Solana死多头，以极高的数据密度著称，专注于Solana及比特币链上数据。', 't', 11, '2025-12-19 07:43:31.870789+00', '2025-12-18 21:29:46+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:06.493113+00', 578000),
('UCN9Nj4tjXbVTLYWN0EKly_Q', '@CryptoBanterGroup', 'Crypto Banter', '直播/交易：直播流之王，每日高频直播，涵盖实时新闻、图表分析及“阿尔法”喊单。', 't', 2, '2025-12-19 07:32:15.420568+00', '2025-12-18 14:59:39+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:33:19.212346+00', 1180000),
('UCQglaVhGOBI0BR5S6IJnQPg', '@Jungernaut', 'Brian Jung', '理财/大众：Web2流量入口，结合个人理财与加密投资，精通算法推荐。', 't', 8, '2025-12-19 07:43:31.870789+00', NULL, '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:15.746593+00', 2090000),
('UCqK_GSMbpiV8spgD3ZGloSw', '@CoinBureau', 'Coin Bureau', '教育/投研：深度投研标杆，提供机构级项目研报和宏观分析，以“无付费推广”著称。', 't', 1, '2025-12-19 07:32:15.420568+00', '2025-12-18 15:01:17+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:33:22.873136+00', 2730000),
('UCQQ_fGcMDxlKre3SEqEWrLA', '@99Bitcoins', '99Bitcoins', '教育/科普：新手百科全书，将复杂概念转化为易懂的动画教程，适合新人入门。', 't', 18, '2025-12-19 07:43:31.870789+00', '2025-12-19 04:59:51+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:43:41.156827+00', 719000),
('UCRvqjQPSeaWn-uEx-w0XOIg', '@intothecryptoverse', 'Benjamin Cowen', '量化/周期：量化风险管理，坚持“无废话”数据分析，利用数学模型预测周期。', 't', 7, '2025-12-19 07:43:31.870789+00', '2025-12-18 20:30:47+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:44:19.386555+00', 969000),
('UCrYmtJBtLdtm2ov84ulV-yg', '@IvanOnTech', 'Ivan on Tech', '技术/开发：技术极客视角，从代码和开发者角度审视项目，关注基础设施升级。', 't', 14, '2025-12-19 07:43:31.870789+00', '2025-12-18 18:19:05+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:43:54.802936+00', 534000),
('UCVVX-7tHff75fRAEEEnZiAQ', '@milesdeutscher1357', 'Miles Deutscher', '空投/DeFi：空投与DeFi专家，专注于如何通过交互协议获取空投及收益策略。', 't', 17, '2025-12-19 07:43:31.870789+00', '2025-12-16 16:31:21+00', '2025-11-24 02:18:42.073657+00', '2025-12-19 07:43:43.520405+00', 225000),
('UCWiiMnsnw5Isc2PP1to9nNw', '@unchainedcrypto', 'unchainedcrypto', NULL, 't', 0, '2025-12-19 07:32:15.420568+00', '2025-12-18 18:00:04+00', '2025-11-25 02:11:08.348071+00', '2025-12-19 07:33:27.743408+00', 72600),
('UCZ3fejCy_P5xhv9QF-V6-YA', '@SheldonEvansx', 'Sheldon Evans', '心理/NFT：思维重塑，不仅讲币，更讲投资心理学和财富思维，侧重NFT叙事。', 't', 20, '2025-12-19 07:47:38.01953+00', NULL, '2025-11-24 02:18:42.073657+00', '2025-12-19 07:47:40.032583+00', 676000);
