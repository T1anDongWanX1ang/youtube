# TP Strategy YouTube 数据镜像

轮询任务会将每个新生成的 YouTube `research_viewpoint` 以相同的
`viewpoint_id` 写入 TP Strategy 的 `research_viewpoint`。写入使用幂等
upsert，因此同一条消息可安全重试；目标表中的 `send_flag` 保持不变，
`synced_at` 会更新。

同时，每轮频道抓取完成后会完整 upsert `youtube_crypto_channels`，包括
`handle`、标题、描述、启用状态、订阅数、轮询时间和 `channel_image`。首次
同步会自动在目标库创建该表，便于下游 SQL 将观点和博主信息/头像关联起来。

连接变量优先级如下：

1. `TP_STRATEGY_DATABASE_URL=mysql://user:password@host:3306/tp_strategy`
2. `TP_STRATEGY_HOST`、`TP_STRATEGY_PORT`、`TP_STRATEGY_USER`、
   `TP_STRATEGY_PASSWORD`、`TP_STRATEGY_DATABASE`
3. 现有本地变量 `TRADE_DB_HOST`、`TRADE_DB_PORT`、`TRADE_DB_USER`、
   `TRADE_DB_PASSWORD`、`TRADE_DB_NAME`

如果未配置目标库，镜像功能会关闭，现有采集流程不受影响。目标库不可用时，
频道同步会记录错误但不会中断 YouTube 采集；观点写入错误会由调用点记录，
避免影响视频分析主流程。
