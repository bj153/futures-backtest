#!/usr/bin/env python3
"""一键发布到远端服务器。

用法:
    python publish.py            # 构建前端 + 打包 + 发布
    python publish.py --no-build # 跳过 pnpm build（只改了后端时用）
    python publish.py --rollback # 回滚到上一个版本

配置: .deploy/token 存放部署令牌；可用环境变量覆盖:
    DEPLOY_URL   默认 http://43.163.192.223:9000
"""
import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DEPLOY_URL = os.environ.get("DEPLOY_URL", "http://43.163.192.223:9000")
TOKEN_FILE = ROOT / ".deploy" / "token"
EXCLUDES = {"__pycache__", "backend.log", "backend_restart.log", "server.log", "logs"}


def load_token() -> str:
    if not TOKEN_FILE.exists():
        sys.exit(f"找不到 {TOKEN_FILE}，请先放入部署令牌")
    return TOKEN_FILE.read_text().strip()


def request(method: str, path: str, data: bytes | None = None) -> dict:
    import json
    req = urllib.request.Request(
        DEPLOY_URL + path, data=data, method=method,
        headers={"Authorization": f"Bearer {load_token()}",
                 "Content-Type": "application/gzip"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"远端返回 {e.code}: {e.read().decode(errors='replace')}")
    except Exception as e:
        sys.exit(f"请求失败: {e}")


def health() -> dict:
    import json
    with urllib.request.urlopen(DEPLOY_URL + "/health", timeout=10) as r:
        return json.loads(r.read())


def build_frontend():
    print("==> pnpm build ...")
    subprocess.run(["pnpm", "build"], cwd=ROOT, check=True, shell=(os.name == "nt"))


def make_package() -> Path:
    print("==> 打包 backend/ + dist/ ...")
    pkg = ROOT / ".deploy" / "release.tar.gz"

    def skip(ti: tarfile.TarInfo):
        parts = set(Path(ti.name).parts)
        return None if parts & EXCLUDES or ti.name.endswith(".pyc") else ti

    with tarfile.open(pkg, "w:gz") as tf:
        tf.add(ROOT / "backend", arcname="backend", filter=skip)
        tf.add(ROOT / "dist", arcname="dist", filter=skip)
    print(f"    {pkg} ({pkg.stat().st_size / 1e6:.1f} MB)")
    return pkg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="跳过前端构建")
    ap.add_argument("--rollback", action="store_true", help="回滚到上一个版本")
    args = ap.parse_args()

    if args.rollback:
        res = request("POST", "/rollback", data=b"")
        print("回滚结果:", res)
        return

    if not args.no_build:
        build_frontend()
    pkg = make_package()
    print(f"==> 发布到 {DEPLOY_URL}/deploy ...")
    res = request("POST", "/deploy", data=pkg.read_bytes())
    print("发布结果:", res)
    pkg.unlink(missing_ok=True)
    if not res.get("backend_alive"):
        sys.exit("!! 主服务健康检查未通过，考虑 python publish.py --rollback")
    print("==> 远端状态:", health())


if __name__ == "__main__":
    main()
