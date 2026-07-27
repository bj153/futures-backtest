#!/usr/bin/env python3
"""deploy v2 · 拉取式部署守护（deploy_watcher.py）

设计原则：服务器零入站端口。本脚本由 systemd timer 每 2 分钟触发一次，
主动出站检查私有 Git 仓库 release 分支是否有新 commit，有则拉取部署。

安全属性：
- 只读 deploy key：服务器上的凭证只能 git fetch，不能 push
- 不执行仓库里的任何脚本：只做 checkout + 拷贝 + 切换软链
- 后端以普通用户运行；重启通过 sudoers 白名单单条命令
- 健康检查失败自动回滚到上一个版本
- 固定部署期望路径结构：backend/ + dist/ 必须在仓库根目录

目录布局（/opt/futures-backtest/）：
  repo/            # git 仓库（长期存在的 working copy）
  releases/<sha>/  # 每次部署的不可变副本
  current -> releases/<sha>
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP = Path("/opt/futures-backtest")
REPO = APP / "repo"
RELEASES = APP / "releases"
CURRENT = APP / "current"
STATE = APP / "watcher_state.json"
BRANCH = os.environ.get("DEPLOY_BRANCH", "release")
BACKEND_SERVICE = "futures-backend"
HEALTH_URL = "http://127.0.0.1:8001/api/contracts"
KEEP = 5

# sudoers 白名单里唯一允许的非 root 提权命令
RESTART_CMD = ["sudo", "-n", "/bin/systemctl", "restart", BACKEND_SERVICE]


def log(msg):
    print(f"[{time.strftime('%F %T')}] {msg}", flush=True)


def run(cmd, cwd=None, timeout=120, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} -> {p.returncode}: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def current_sha():
    if STATE.exists():
        return json.loads(STATE.read_text()).get("sha", "")
    return ""


def save_state(sha):
    STATE.write_text(json.dumps({"sha": sha, "ts": time.strftime("%F %T")}))


def backend_alive():
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def restart_and_wait():
    run(RESTART_CMD, timeout=60)
    for _ in range(30):
        time.sleep(2)
        if backend_alive():
            return True
    return False


def deploy(sha):
    """checkout sha -> releases/<sha> -> 切换 current -> 重启"""
    run(["git", "fetch", "--depth", "50", "origin", BRANCH], cwd=REPO, timeout=180)
    run(["git", "checkout", "--force", sha], cwd=REPO)

    # 结构校验：防止异常仓库内容被部署
    for required in ("backend/main.py", "dist/index.html"):
        if not (REPO / required).exists():
            raise RuntimeError(f"仓库结构不符，缺少 {required}，拒绝部署")

    dest = RELEASES / sha
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REPO, dest,
                    ignore=shutil.ignore_patterns(".git", "data", "__pycache__", "*.log"))
    # .env 不进入 Git，从 current 旧版本继承（首次由 install 脚本放置）
    env_src = CURRENT / "backend" / ".env"
    env_dst = dest / "backend" / ".env"
    if env_src.exists() and not env_dst.exists():
        shutil.copy2(env_src, env_dst)

    os.symlink(dest, str(CURRENT) + ".tmp")
    os.replace(str(CURRENT) + ".tmp", CURRENT)
    return restart_and_wait()


def rollback(prev_sha):
    log(f"回滚到 {prev_sha[:8]}")
    os.symlink(RELEASES / prev_sha, str(CURRENT) + ".tmp")
    os.replace(str(CURRENT) + ".tmp", CURRENT)
    ok = restart_and_wait()
    save_state(prev_sha)
    return ok


def main():
    remote = run(["git", "ls-remote", "origin", BRANCH], cwd=REPO, timeout=60)
    if not remote:
        log(f"远端无 {BRANCH} 分支，跳过")
        return 0
    sha = remote.split()[0]
    local = current_sha()
    if sha == local:
        return 0  # 无新版本，安静退出

    log(f"发现新版本 {sha[:8]}（当前 {local[:8] or '无'}），开始部署")
    try:
        if deploy(sha):
            save_state(sha)
            log(f"部署成功 {sha[:8]}")
            # 清理旧版本
            dirs = sorted((d for d in RELEASES.iterdir() if d.is_dir()), key=lambda d: d.name)
            for d in dirs[:-KEEP]:
                if d.name != local:
                    shutil.rmtree(d, ignore_errors=True)
        else:
            log("健康检查失败")
            if local and (RELEASES / local).exists():
                rollback(local)
            return 1
    except Exception as e:
        log(f"部署异常: {e}")
        if local and (RELEASES / local).exists() and os.readlink(CURRENT) != str(RELEASES / local):
            rollback(local)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
