"""Redis 远端命令的构造、采集与 redis-cli 预检（原始输出不进大模型）。

`_redis_cmd` 负责拼命令行（host/port/认证）；四个 collect_* 各跑一条采集命令、把原始输出落盘
（dumps/metrics/）并返回，再由 parse_metrics/redis/ 的各维度解析器解析、rules/redis/ 的规则引擎
判级。网络延时在 Java 服务器（主 SSH）上测，其余三项在 Redis 机器（REDIS_SSH）上测。

`ensure_redis_cli` 是采集前的预检：确认目标机器有 redis-cli，没有则经人工确认后上传并运行
asset/shell/redis-cli-install.sh。它内含 langgraph `interrupt()`，必须由调用方在并发采集
之前调用（并发线程里中断无法回填）。

本模块是 redis 三层里的采集层：解析在 parse_metrics/redis/、规则计算在 rules/redis/，本层负责
"把原始输出弄回来"。它带副作用（SSH、上传安装脚本），不归那两层。
"""
import os
from typing import Optional

import paramiko
from langgraph.types import interrupt

from config.config import SSH, REDIS_SSH, _MEASURE_SECONDS, _MEASURE_INTERVAL_SECONDS, METRICS_STORE_DIR
from util._common import cap, write_text, get_metric_store_path
from util.ssh_client import run_cmd
from util.log import get_logger

_REDIS_HOST = os.getenv("REDIS_HOST", os.getenv("SSH_HOST", "127.0.0.1"))
_REDIS_PORT = os.getenv("REDIS_PORT", "6379")
_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# redis-cli 缺失时上传的安装脚本。注意这是 __file__ 相对路径：改本模块所在目录深度时要同步改 ".." 的层数
_LOCAL_INSTALL_SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "asset", "shell", "redis-cli-install.sh"
))
_REMOTE_UPLOAD_DIR = "/tmp/redis-cli-install.sh"

logger = get_logger(__name__)


def _redis_cmd(sub: str, cli: str = "redis-cli") -> str:
    # 用 env 而不是裸的变量赋值：这条命令可能被 timeout/stdbuf 这类直接 exec 的程序包住，
    # 那时 `VAR=x cmd` 会被当成程序名去找（timeout: failed to run command ...）。
    env = f"env REDISCLI_AUTH='{_REDIS_PASSWORD}' " if _REDIS_PASSWORD else ""
    return f"{env}{cli} -h {_REDIS_HOST} -p {_REDIS_PORT} {sub}"


# ----------------------------------------------------------------- 采集（原文不进大模型）

def collect_net_latency(cli: str = "redis-cli") -> str:
    """测 Java 服务器到 Redis 的网络延时，持续 1 分钟。返回原始输出（供解析）。"""
    logger.info("开始采集访问redis的网络延时数据（将持续采集%d秒后再返回）", _MEASURE_SECONDS)
    # -i N 的语义是「采样 N 秒 → 在窗口结束时打印唯一一行汇总 → 退出」
    # timeout 的超时要大于 i N 的超时，否则无输出：因为 timeout 从 exec 之前就开始计时、必然早到几个毫秒。
    cmd = (
        f"timeout {_MEASURE_SECONDS+30} "
        f"{_redis_cmd(f'-i {_MEASURE_SECONDS} --latency', cli=cli)} 2>&1"
    )
    result = cap(run_cmd(cmd, timeout=_MEASURE_SECONDS + 60), max_lines=80, max_chars=8000)
    logger.debug("网络延时原始输出：\n%s", result)

    persit_result=result
    if not result.startswith(("命令无输出", "SSH 执行失败")):
        persit_result = f"[单位毫秒，格式：min max avg 采样数]\n{result}"

    write_text(get_metric_store_path("redis_net_latency"), persit_result)

    return result


def collect_intrinsic_latency(cli: str = "redis-cli") -> str:
    """测 Redis 服务器固有延时，持续 1 分钟（在 Redis 所在机器上执行 redis-cli --intrinsic-latency）。"""
    logger.info("开始采集redis服务器固有延时数据（将持续采集%d秒后再返回）", _MEASURE_SECONDS)
    cmd = f"{cli} --intrinsic-latency {_MEASURE_SECONDS}"
    result = cap(run_cmd(cmd, timeout=_MEASURE_SECONDS + 30, ssh_config=REDIS_SSH), max_lines=80, max_chars=8000)
    logger.debug("固有延时原始输出：\n%s", result)

    write_text(get_metric_store_path("redis_intrinsic_latency"), result)

    return result


def collect_slowlog(cli: str = "redis-cli", count: int = 128) -> str:
    """查看 Redis 慢日志，返回原始输出（供解析）。

    redis-cli 的 stdout 非 tty 时走 raw 输出，空数组一个字符都不打印，run_cmd 只会给出
    含糊的「命令无输出」，与「没有慢日志」区分不开。所以先取条数、再取明细，两段各带标题
    让 stdout 永不为空；2>&1 把 NOAUTH/连接失败一起带回。
    """
    logger.info("开始采集redis慢日志数据")
    cmd = (
        f"echo '[slowlog len]'; {_redis_cmd('slowlog len', cli=cli)} 2>&1; "
        f"echo '[slowlog get {count}]'; {_redis_cmd(f'slowlog get {count}', cli=cli)} 2>&1"
    )
    # 原文不再交给大模型，只进解析器，放宽截断以保留更完整的慢日志窗口
    result = cap(run_cmd(cmd, ssh_config=REDIS_SSH), max_lines=3000, max_chars=300000)
    logger.debug("慢日志原始输出：\n%s", result)

    write_text(get_metric_store_path("redis_slowlog"), result)

    return result


def collect_cpu_usage() -> str:
    """采集 Redis 服务器整机 CPU 使用率，持续 60 秒（每 5 秒一次，共 12 次采样）。"""
    n = max(1, _MEASURE_SECONDS // _MEASURE_INTERVAL_SECONDS)   # 60/5 = 12
    iv = _MEASURE_INTERVAL_SECONDS
    # 只用 top：批处理模式每 iv 秒出一轮，共 n 轮约 60 秒；grep 只保留整机 CPU 的 %Cpu 行
    cmd = f"top -b -d {iv} -n {n} | grep -E '%Cpu'"
    logger.info("开始采集redis服务器[%s]的CPU使用率（将持续%d秒，每%d秒采集一次，共%d次）",
                REDIS_SSH["host"], _MEASURE_SECONDS, _MEASURE_INTERVAL_SECONDS, n)
    result = cap(run_cmd(cmd, timeout=_MEASURE_SECONDS + 30, ssh_config=REDIS_SSH), max_lines=80, max_chars=8000)
    logger.debug("CPU 使用率原始输出：\n%s", result)

    write_text(get_metric_store_path("redis_cpu_usage"),result)

    return result


# ----------------------------------------------------------------- 预检（含人工在环中断点）

def ensure_redis_cli(ssh_config: Optional[dict] = None) -> str:
    """服务器上有 redis-cli。
    没有则上传并运行 asset/shell/redis-cli-install.sh。返回可用命令名或错误说明。
    """
    cfg = ssh_config or SSH
    logger.info("检查服务器%s上有无redis-cli", cfg["host"])
    have = run_cmd(cmd="command -v redis-cli 2>/dev/null", ssh_config=cfg).strip()

    err_msg = ""
    if have.startswith("/"):
        logger.info("服务器%s上已存在redis-cli", cfg["host"])
        return "redis-cli"
    if not os.path.exists(_LOCAL_INSTALL_SCRIPT):
        err_msg = f"(服务器{cfg['host']}无 redis-cli，且本地 asset/shell/redis-cli-install.sh 不存在)"
        logger.warning(err_msg)
        return err_msg

    # 人工在环：上传+安装是落到目标服务器的写操作，先让用户确认
    answer = interrupt({
        "question": f"服务器 {cfg['host']} 上没有 redis-cli，确认上传并安装吗？(y/n)",
        "detail": (
            f"1、目标服务器：{cfg['username']}@{cfg['host']}:{cfg['port']}\n"
            f"2、操作：上传 asset/shell/redis-cli-install.sh 到 /tmp 并执行\n"
            f"3、该脚本是Redis 官方提供的一个安装脚本：会自动检测服务器的操作系统和架构，下载适配的 redis-cli进行安装。(要求该目标服务器能联网)\n"
            f"4、默认会安装在目标服务器的/usr/local/bin目录下。使用结束后的卸载：直接删除/usr/local/bin目录下的redis-cli即可。\n"
            f"5、您也可以自行手动安装redis-cli，然后输入n继续。系统会再次检测。\n"
        ),
    })
    if str(answer).strip().lower() not in ("y", "yes"):
        err_msg = f"(人工未确认在服务器{cfg['host']}上传并安装 redis-cli，操作已取消)"
        logger.warning(err_msg)
        return err_msg

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg["username"],
            password=cfg["password"],
            timeout=10,
        )
        sftp = client.open_sftp()
        try:
            sftp.put(_LOCAL_INSTALL_SCRIPT, _REMOTE_UPLOAD_DIR)
        finally:
            sftp.close()
    except Exception as e:
        err_msg = f"(往服务器{cfg['host']}上传redis-cli-install.sh失败: {e})"
        logger.warning(err_msg)
        return err_msg
    finally:
        client.close()

    logger.info("已上传redis-cli的安装脚本到%s机器的%s目录", cfg['host'], _REMOTE_UPLOAD_DIR)
    run_cmd(
        cmd=f"chmod +x /tmp/redis-cli-install.sh && bash /tmp/redis-cli-install.sh",
        timeout=300,
        ssh_config=cfg
    )
    have = run_cmd("command -v redis-cli 2>/dev/null", ssh_config=cfg).strip()

    if have.startswith("/"):
        logger.info("已安装redis-cli到%s机器的/usr/local/bin目录", cfg['host'])
        return "redis-cli"
    else:
        err_msg = f"(智能体往服务器{cfg['host']}上安装redis-cli失败：{have})"
        logger.warning(err_msg)
        return err_msg


