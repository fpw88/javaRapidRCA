"""MySQL 深入排查工具。"""
import os

from langchain.tools import tool

from util._common import cap
from util.ssh_client import run_cmd

_MYSQL_HOST = os.getenv("MYSQL_HOST", os.getenv("SSH_HOST", "127.0.0.1"))
_MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
_MYSQL_USER = os.getenv("MYSQL_USER", "root")
_MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")


def _mysql_cmd(sql: str) -> str:
    env = f"MYSQL_PWD='{_MYSQL_PASSWORD}' " if _MYSQL_PASSWORD else ""
    return f"{env}mysql -h {_MYSQL_HOST} -P {_MYSQL_PORT} -u {_MYSQL_USER} -e \"{sql}\""


@tool
def get_mysql_processlist() -> str:
    """查看 MySQL 当前连接与正在执行的 SQL（SHOW FULL PROCESSLIST）。"""
    return cap(run_cmd(_mysql_cmd("SHOW FULL PROCESSLIST")), max_lines=80)


@tool
def get_mysql_innodb_status() -> str:
    """查看 InnoDB 引擎状态（锁/事务/缓冲池）。"""
    return cap(run_cmd(_mysql_cmd("SHOW ENGINE INNODB STATUS\\G")), max_lines=150, max_chars=8000)


@tool
def get_mysql_slow_queries(limit: int = 20) -> str:
    """查看 MySQL 慢查询日志尾部（需已开启 slow_query_log）。"""
    cmd = f"tail -n {limit} /var/log/mysql/mysql-slow.log 2>/dev/null || echo '(未找到慢日志文件)'"
    return cap(run_cmd(cmd), max_lines=60)
