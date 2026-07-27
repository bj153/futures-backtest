#!/usr/bin/env bash
# deploy v2 安装脚本（全新/重装后的服务器上，root 执行一次）
# 前置条件：已有一个云端私有 Git 仓库（GitHub/Gitee），并生成了只读 deploy key
set -euo pipefail

REPO_URL="${1:?用法: bash install_v2.sh <git仓库SSH地址>  例: bash install_v2.sh git@github.com:you/futures-backtest.git}"
APP=/opt/futures-backtest

echo "==> 创建低权限用户 fbapp"
id fbapp 2>/dev/null || useradd -r -s /usr/sbin/nologin -d "$APP" fbapp

mkdir -p "$APP"/{releases,data}
cd "$APP"

echo "==> 克隆仓库（release 分支）"
# fbapp 的 home 是 /opt/futures-backtest，SSH key 放在其 .ssh 下
mkdir -p "$APP/.ssh"
if [ ! -f "$APP/.ssh/id_ed25519" ]; then
  echo "!! 请先生成 deploy key 并把公钥配到 GitHub 仓库（Settings → Deploy keys，只读）："
  echo "   ssh-keygen -t ed25519 -f $APP/.ssh/id_ed25519 -N '' -C futures-deploy"
  echo "   cat $APP/.ssh/id_ed25519.pub"
  exit 1
fi
chmod 700 "$APP/.ssh"; chmod 600 "$APP/.ssh/id_ed25519"
ssh-keyscan github.com >> "$APP/.ssh/known_hosts" 2>/dev/null
if [ ! -d "$APP/repo/.git" ]; then
  sudo -u fbapp git clone --branch release --single-branch "$REPO_URL" "$APP/repo"
fi

echo "==> Python 环境"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --upgrade pip -q
"$APP/venv/bin/pip" install -q -r "$APP/repo/backend/requirements.txt"

echo "==> 放置 .env（不进 Git，手动放一次）"
if [ ! -f "$APP/repo/backend/.env" ]; then
  echo "!! 请把生产 .env 放到 $APP/repo/backend/.env（首次部署会继承到各 release）"
fi

echo "==> watcher 脚本"
cp "$(dirname "$0")/deploy_watcher.py" "$APP/deploy_watcher.py"

echo "==> sudoers：仅允许 fbapp 重启 futures-backend 一条命令"
cat > /etc/sudoers.d/futures-deploy <<'EOF'
fbapp ALL=(root) NOPASSWD: /bin/systemctl restart futures-backend
EOF
chmod 440 /etc/sudoers.d/futures-deploy

echo "==> systemd 单元"
cp "$(dirname "$0")"/futures-backend.service /etc/systemd/system/
cp "$(dirname "$0")"/futures-watcher.service /etc/systemd/system/
cp "$(dirname "$0")"/futures-watcher.timer /etc/systemd/system/

chown -R fbapp:fbapp "$APP"
systemctl daemon-reload
systemctl enable --now futures-watcher.timer
echo "==> 手动触发首次部署"
sudo -u fbapp "$APP/venv/bin/python" "$APP/deploy_watcher.py" || true
systemctl enable --now futures-backend

echo ""
echo "================ 完成 ================"
echo "安全组只需要放行 8001（网站访问，建议也限制 IP）。9000/22/5432 全部不需要对公网。"
echo "查看部署日志: journalctl -u futures-watcher -n 20 --no-pager"
echo "查看后端日志: journalctl -u futures-backend -n 50 --no-pager"
