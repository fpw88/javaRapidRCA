"""SSH 封装：用 paramiko 执行远程命令（不考虑安全性）。

两层：`ssh_exec` 返回 (stdout, stderr) 原始二元组；`run_cmd` 是给各维度诊断工具用的便捷封装，
只返回 stdout，无输出时把 stderr 当成说明返回（调用方不必再判空）。
"""
from typing import Optional

import paramiko

from config.config import SSH


def ssh_exec(command: str, timeout: int = 60, ssh_config: Optional[dict] = None) -> tuple[str, str]:
    """执行一条远程命令，返回 (stdout, stderr)。异常时错误信息放进 stderr。ssh_config 缺省用 config.SSH。"""
    cfg = ssh_config or SSH
    client = paramiko.SSHClient()
    # 自动接受未知主机密钥 —— 简单起见，不做 host key 校验
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg["username"],
            password=cfg["password"],
            timeout=10,
        )
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err
    except Exception as e:  # 连接/执行失败统一返回
        return "", f"SSH 执行失败: {e}"
    finally:
        client.close()


def run_cmd(cmd: str, timeout: int = 90, ssh_config: Optional[dict] = None) -> str:
    """执行远程命令，返回 stdout；无输出时返回 stderr 说明。ssh_config 缺省用主 SSH。"""
    out, err = ssh_exec(cmd, timeout=timeout, ssh_config=ssh_config)
    if out.strip():
        return out.strip()
    return "命令无输出" + (": " + err.strip() if err.strip() else "")
