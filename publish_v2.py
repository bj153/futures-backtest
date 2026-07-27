#!/usr/bin/env python3
"""deploy v2 · 本地发布脚本（publish_v2.py）

发布 = 构建前端 → 把 backend/ + dist/ 提交到私有仓库的 release 分支 → push。
服务器上的 watcher 每 2 分钟自动拉取部署，本脚本推完即可。

首次配置（一次性）：
  git clone <私有仓库地址> .deploy/release-repo
  cd .deploy/release-repo && git checkout -b release
然后运行: python publish_v2.py
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PNPM = shutil.which("pnpm") or "pnpm.cmd"

ROOT = Path(__file__).parent
REPO = ROOT / ".deploy" / "release-repo"
EXCLUDES = {"__pycache__", "logs"}


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       errors="replace", shell=False)
    if check and p.returncode != 0:
        sys.exit(f"失败: {' '.join(cmd)}\n{p.stderr.strip()[:500]}")
    return (p.stdout or "").strip()


def main():
    if not (REPO / ".git").exists():
        sys.exit(f"未找到 {REPO}，先执行:\n"
                 f"  git clone <私有仓库地址> .deploy/release-repo\n"
                 f"  cd .deploy/release-repo && git checkout -b release")

    print("==> pnpm build ...")
    run([PNPM, "build"], cwd=ROOT)

    print("==> 同步 backend/ + dist/ 到 release 仓库 ...")
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO)
    if branch != "release":
        run(["git", "checkout", "release"], cwd=REPO)

    def sync(src, dst):
        dst.mkdir(exist_ok=True)
        for item in dst.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        for item in src.iterdir():
            if item.name in EXCLUDES or item.suffix == ".pyc" or item.suffix == ".log":
                continue
            if item.name == ".env":
                continue  # .env 不进 Git
            if item.is_dir():
                shutil.copytree(item, dst / item.name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log"))
            else:
                shutil.copy2(item, dst / item.name)

    sync(ROOT / "backend", REPO / "backend")
    sync(ROOT / "dist", REPO / "dist")

    run(["git", "add", "-A"], cwd=REPO)
    status = run(["git", "status", "--porcelain"], cwd=REPO)
    if not status:
        print("==> 无变更，无需发布")
        return
    msg = f"release {time.strftime('%Y%m%d-%H%M%S')}"
    run(["git", "commit", "-m", msg], cwd=REPO)
    run(["git", "push", "origin", "release"], cwd=REPO)
    sha = run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO)
    print(f"==> 已推送 {sha}（{msg}）")
    print("服务器 watcher 每 2 分钟检查一次；journalctl -u futures-watcher -f 可观察部署过程")


if __name__ == "__main__":
    main()
