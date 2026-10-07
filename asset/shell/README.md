# 传给目标服务器用的脚本文件。

- `redis-cli-install.sh`：Java 服务器缺少 `redis-cli` 时，`diagnose_redis`（内部 `_ensure_redis_cli`）会通过 SFTP 把它传到服务器并执行，装好 `redis-cli` 后跑 `--latency` 测网络延时。
  - 该脚本是Redis 官方提供的一个安装脚本：会自动检测服务器的操作系统和架构，下载对应的 redis-cli进行安装。
  - 默认会安装在/usr/local/bin目录下。 安装完成后，直接输入 redis-cli 即可使用。
  - 如何卸载：直接删除/usr/local/bin目录下的redis-cli即可
