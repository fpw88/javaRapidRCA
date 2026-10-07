from config.config import LOG_LEVEL
from tools.redis_tools import diagnose_redis
from util.log import setup_logging

if __name__ == "__main__":
    setup_logging(LOG_LEVEL)

    # 单入口：采集四因子 → 解析判级 → 返回结构化摘要（原始输出不进大模型）
    result = diagnose_redis.func()
    print(result)

    print("========结束")
