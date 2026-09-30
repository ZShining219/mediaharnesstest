#!/usr/bin/env python3
"""部署到生产服务器 (Docker)。

用法:
    SSH_PASS=服务器密码 uv run --with paramiko scripts/deploy_server.py
    # 或已配置 ssh 免密:  uv run scripts/deploy_server.py --host 103.52.153.212

流程: 打包项目(排除 venv/产物) -> SFTP 上传 -> 解压 -> docker compose build/up
"""
import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = "/opt/aimf"

EXCLUDE = {".venv", "__pycache__", ".git", "outputs/tmp", "data/jobs.db",
           "services/ComfyUI", "services/MoneyPrinterTurbo",
           ".env", "config.yaml"}  # 服务器自己的配置, 不覆盖


def make_tarball() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "aimf.tar.gz"
    def keep(ti):
        rel = ti.name
        if rel.startswith("./"):
            rel = rel[2:]          # "./.env" -> ".env" (不能用 lstrip, 会吃掉 .env 的点)
        if rel.startswith("/"):
            rel = rel[1:]
        if any(rel == e or rel.startswith(e + "/") for e in EXCLUDE):
            return None
        # 排除各服务虚拟环境与浏览器缓存
        if "/.venv" in rel or rel.endswith(".pyc") or "/cookies/" in rel:
            return None
        return ti
    with tarfile.open(tmp, "w:gz") as t:
        t.add(ROOT, arcname=".", filter=keep)
    return tmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="103.52.153.212")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default=os.getenv("SSH_PASS"))
    args = ap.parse_args()

    import paramiko
    print("==> 打包项目")
    tar = make_tarball()
    print(f"    {tar} ({tar.stat().st_size / 1e6:.1f} MB)")

    print(f"==> 连接 {args.host}")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(args.host, port=args.port, username=args.user,
              password=args.password, timeout=20,
              look_for_keys=bool(not args.password), allow_agent=bool(not args.password))

    def run(cmd, show=True, timeout=600):
        print(f"    $ {cmd[:110]}")
        _, out, err = c.exec_command(cmd, timeout=timeout, get_pty=False)
        o, e = out.read().decode(), err.read().decode()
        code = out.channel.recv_exit_status()
        if show and (o.strip() or e.strip()):
            print((o + e)[-1500:])
        if code != 0:
            raise RuntimeError(f"命令失败({code}): {cmd}\n{e[-800:]}")
        return o

    print("==> 上传")
    run(f"mkdir -p {REMOTE_DIR}")
    sftp = c.open_sftp()
    remote_tar = f"{REMOTE_DIR}/aimf.tar.gz"
    sftp.put(str(tar), remote_tar)
    sftp.close()

    print("==> 解压")
    run(f"cd {REMOTE_DIR} && tar xzf aimf.tar.gz && rm aimf.tar.gz")

    print("==> 准备配置 (不覆盖已存在的 .env / config.yaml)")
    run(f"cd {REMOTE_DIR} && [ -f .env ] || cp .env.example .env")
    run(f"cd {REMOTE_DIR} && [ -f config.yaml ] || cp config.example.yaml config.yaml")
    run(f"cd {REMOTE_DIR} && mkdir -p outputs/tmp data assets")

    print("==> Docker 构建 (首次较慢)")
    run(f"cd {REMOTE_DIR} && docker compose build --quiet", timeout=1800)
    run(f"cd {REMOTE_DIR} && docker compose up -d")
    time.sleep(3)
    run("docker ps --filter name=aimf-app")
    run("curl -s --max-time 10 http://127.0.0.1:8800/api/health || true")
    c.close()
    print(f"""
✅ 部署完成
   访问: http://{args.host}:8800   (建议尽快在 .env 设置 ORCH_TOKEN)
   日志: ssh {args.user}@{args.host} 'docker logs -f aimf-app'
   抖音登录: docker exec -it aimf-app sau douyin login --account main
""")


if __name__ == "__main__":
    sys.exit(main())
