# YouTube Crypto Agent

YouTube 加密频道自动监控与分析工具，使用 Gemini 3.0 Pro 对加密货币相关的 YouTube 视频进行结构化分析。

## 系统要求

- **Python 3.11+** （必需）
- Doris / MySQL 兼容数据库（使用 MySQL 协议）
- [uv](https://github.com/astral-sh/uv) 包管理工具

## 功能

- 定期监控配置的 YouTube 加密频道
- 自动获取新上传的视频（通过 YouTube Data API v3）
- 使用 Gemini 3.0 Pro 对视频内容进行结构化分析
- 提取关键信息：摘要、情绪、提及的 Token、叙事标签等
- 结果存储到 Doris / MySQL 兼容数据库

## 快速开始

### 1. 安装依赖

确保你已经安装了 Python 3.11+ 和 uv，然后在项目目录下运行：

```bash
uv sync
```

这会自动创建虚拟环境并安装所有依赖。

### 2. 环境配置

复制配置模板并编辑：

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置以下必需变量（Doris/MySQL 连接字符串示例：`mysql://user:password@host:port/database`，如果密码中包含 `@` 请 URL 编码成 `%40`）：

```bash
# YouTube Data API v3 密钥
# 获取地址：https://console.cloud.google.com/apis/credentials
YOUTUBE_DATA_API_KEY=your_youtube_api_key_here

# Gemini API 密钥
# 获取地址：https://aistudio.google.com/app/apikey
YOUTUBE_GEMINI_API_KEY=your_gemini_api_key_here

# Doris/MySQL 数据库连接
DATABASE_URL=mysql://user:password@host:3306/database_name

# 可选：数据库连接池配置
DB_MIN_POOL_SIZE=2
DB_MAX_POOL_SIZE=10
```

### 3. 初始化数据库

当前仓库附带的是 PostgreSQL 示例 schema（`doc/20251121_youtube_crypto_schema.sql`）。请根据 Doris 语法创建等价的表：

- `youtube_crypto_channels`
- `youtube_crypto_videos` （`video_id` 唯一键，存储 tags/metadata 可使用 TEXT/JSON）
- `youtube_crypto_video_analyses`（可将数组/JSON 字段改为 TEXT/JSON）

创建完表后，插入要监控的频道列表（`is_active=1` 表示启用）。

### 4. 运行

在项目目录下运行：

```bash
uv run python -m youtube_crypto
```

程序会持续运行，默认每 5 分钟（300 秒）执行一次完整的轮询和分析循环。

按 `Ctrl+C` 停止程序。

## 配置说明

### 环境变量

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `YOUTUBE_DATA_API_KEY` | ✅ | - | YouTube Data API v3 密钥 |
| `YOUTUBE_GEMINI_API_KEY` | ✅ | - | Gemini API 密钥 |
| `DATABASE_URL` | ✅ | - | Doris/MySQL 连接字符串 |
| `YOUTUBE_GEMINI_MODEL` | ❌ | `gemini-2.5-flash-lite` | claims 抽取模型 |
| `YOUTUBE_TRANSCRIBE_MODEL` | ❌ | `gemini-2.5-flash-lite` | 视频转录模型 |
| `YOUTUBE_LOOKBACK_DAYS` | ❌ | 1 | 增量处理回溯天数；临时回填 3 天时手动改成 3 |
| `YOUTUBE_TRANSCRIBE_BATCH_SIZE` | ❌ | 50 | 每轮最多转录视频数 |
| `YOUTUBE_DAILY_TRANSCRIBE_LIMIT` | ❌ | 50 | 每天最多新增 transcript 数，防止循环任务重复烧成本 |
| `YOUTUBE_TRANSCRIBE_CANDIDATE_POOL_MULTIPLIER` | ❌ | 10 | 元数据候选池倍数，默认 50*10=500 条候选再打分 |
| `DB_MIN_POOL_SIZE` | ❌ | 2 | 数据库连接池最小连接数 |
| `DB_MAX_POOL_SIZE` | ❌ | 10 | 数据库连接池最大连接数 |

### 默认常量（可被环境变量覆盖）

- `GEMINI_MODEL_NAME = "gemini-2.5-flash-lite"` - 默认 Gemini 模型
- `ANALYSIS_BATCH_SIZE = 100` - 每次分析的最大视频数
- `LOOKBACK_DAYS = 1` - 增量回溯天数
- `TRANSCRIBE_BATCH_SIZE = 50` - 每轮最多转录视频数
- `MIN_DURATION_SECONDS = 180` - 最小视频时长（过滤掉短视频）

## 工作流程

1. **发现新视频**
   - 从 `youtube_crypto_channels` 表读取所有 `is_active=true` 的频道
   - 通过 YouTube Data API v3 获取各频道的 uploads 播放列表
   - 拉取最近 N 天（`LOOKBACK_DAYS`）的新视频
   - 写入 `youtube_crypto_videos` 表，状态设为 `pending`

2. **转录视频（全文字幕）**
   - 增量默认只取近 1 天、`pending/failed`、尚无字幕、>=180 秒的视频池
   - 转录前先做价值筛选和分类配额：政治/地缘 40%，宏观/市场 30%，商业科技 20%，加密 10%
   - 默认每天最多新增 50 条 transcript；如果当天已经处理过，会自动向下补候选，不会重复转录已有 transcript 的视频
   - 用 Gemini（`YOUTUBE_TRANSCRIBE_MODEL`，默认 `gemini-2.5-flash-lite`）转出带时间戳的逐字稿
   - 长视频会自动「续写」补齐，并做覆盖度校验；不达标记 `coverage_ok=false`，不进入分析
   - 写入 `youtube_crypto_video_transcripts` 表（与分析解耦，是分析读取的唯一底稿）

3. **分析视频（claim 抽取）**
   - 选取 `pending/failed` 且已有合格字幕（`coverage_ok=true`）的视频
   - 调用 Gemini（`YOUTUBE_GEMINI_MODEL`，默认 `gemini-2.5-flash-lite`），**输入是字幕文本**（不再二次观看视频、不再单独跑 router 分类）
   - 返回结构化 JSON：`claims[]`（可证伪观点：资产/方向/目标位/时间窗/原话/时间戳/验证条件）、`events_referenced`、`catalysts_mentioned` 等，并保留旧字段（摘要/情绪/Token/叙事）向后兼容

4. **存储结果**
   - 将分析结果写入 `youtube_crypto_video_analyses` 表（新增 `claims_json` 等列）
   - 更新视频状态为 `completed`
   - 记录 token 用量和处理耗时

## 数据表结构

- **youtube_crypto_channels** - 监控的频道列表
- **youtube_crypto_videos** - 视频元数据和分析状态
- **youtube_crypto_video_analyses** - 视频分析结果（支持版本化）

详细表结构见：`doc/20251121_youtube_crypto_schema.sql`

## 项目结构

```
youtube_crypto/
├── config/          # 配置和环境变量
├── models/          # Pydantic 数据模型
├── repositories/    # 数据库访问层
├── services/        # 业务逻辑（YouTube API、Gemini API）
├── utils/           # 工具函数
├── jobs/            # 定时任务入口
├── prompts/         # Gemini 提示词
└── doc/             # 数据库表结构
```

## 依赖项

核心依赖（自动通过 `uv sync` 安装）：
- `pydantic` - 数据模型和验证
- `asyncpg` - PostgreSQL 异步驱动
- `google-genai` - Gemini API 客户端
- `google-api-python-client` - YouTube Data API v3
