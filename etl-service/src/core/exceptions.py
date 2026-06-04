"""
ETL 服务异常分类体系

设计原则：
- RetryableError：可重试（网络/DB临时故障），按退避策略重试
- FatalError：不可重试（数据格式错误/清洗代码异常），进死信目录
- SkipFileError：跳过（空文件/重复文件），标记 SKIPPED
- DataQualityError：单行数据格式错误，根据 on_row_error 配置决定跳过或回滚
- ConfigValidationError：配置校验失败，拒绝热加载，保留旧配置
- SandboxError：清洗代码执行失败（语法错误/超时/非法返回值）
"""

# 重试退避（秒）：retry_count → 等待秒数
RETRY_BACKOFF = {1: 5, 2: 30, 3: 120}


class ETLError(Exception):
    """ETL 服务基础异常"""
    pass


class RetryableError(ETLError):
    """可重试错误：网络超时、DB 连接断开、文件被占用
    → 按退避策略重试，retry_count 自增
    """
    pass


class FatalError(ETLError):
    """不可重试错误：配置错误、SQL 语法错误、加密密钥无效
    → 不重试，进死信目录，触发告警
    """
    pass


class SkipFileError(ETLError):
    """跳过文件：空文件、格式不支持、已处理
    → 标记 SKIPPED，不重试，不入死信
    """
    pass


class DataQualityError(ETLError):
    """单行数据格式错误
    → 根据 on_row_error 配置决定跳过（skip）或回滚（abort）
    """
    pass


class ConfigValidationError(ETLError):
    """配置校验失败
    → 拒绝热加载，保留旧配置，记录 ERROR 日志
    """
    pass


class SandboxError(FatalError):
    """清洗代码执行失败（语法错误、超时、非法返回值）
    → 继承 FatalError，不重试
    """
    pass
