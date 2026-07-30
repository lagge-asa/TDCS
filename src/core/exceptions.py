"""
ETL 服务异常分类体系。

设计原则：
- RetryableError：可重试（网络/DB临时故障），按退避策略重试
- FatalError：不可重试（数据格式错误/清洗代码异常），进死信目录
- SkipFileError：跳过（空文件/重复文件），标记 SKIPPED
- ConfigValidationError：配置校验失败，拒绝热加载，保留旧配置
- SandboxError：清洗代码执行失败（语法错误/超时/非法返回值）
"""

# 与现有 WorkerPool 的退避策略保持兼容；键为第几次重试。
RETRY_BACKOFF = {1: 5, 2: 30, 3: 120}


class ETLError(Exception):
    """ETL 服务基础异常。"""


class RetryableError(ETLError):
    """可重试错误：网络超时、DB 连接断开、文件被占用。"""


class FatalError(ETLError):
    """不可重试错误：配置错误、SQL 错误、加密密钥无效。"""


class SkipFileError(ETLError):
    """跳过文件：空文件、格式不支持、已处理。"""


class DataQualityError(ETLError):
    """数据质量错误，保留为公共异常类型供调用方分类处理。"""


class ConfigValidationError(ETLError):
    """配置校验失败，拒绝热加载并保留旧配置。"""


class SandboxError(FatalError):
    """清洗代码执行失败，属于不可重试错误。"""
