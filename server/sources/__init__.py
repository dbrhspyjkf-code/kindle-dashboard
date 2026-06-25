"""数据源采集器。

统一接口:每个模块的 collect(cfg) -> dict | None
  - 返回要 merge 进全局 cache 的片段(如 {"weather_now":..., "weather_daily":...});
  - 未配置 / 未启用 / 采集失败 → 返回 None(诚实降级,绝不抛到主循环)。
主循环:for src in SOURCES: cache.update(src.collect(cfg) or {})

设备监控(devices)走单独路径:本机直读在 metrics.py,远端推由 API 接收。
"""
