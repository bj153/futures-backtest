# deploy v2 · 拉取式安全部署

## 架构

```
本地:  python publish_v2.py  →  build + push 到私有仓库 release 分支
服务器: systemd timer 每 2 分钟跑 deploy_watcher.py
        → 发现新 commit → 拉取 → releases/<sha> → 切 current → 重启 → 健康检查 → 失败自动回滚
```

## 与 v1 的安全对比

| | v1（已废） | v2 |
|---|---|---|
| 入站端口 | 9000 公网 | **零**（纯出站 443） |
| 凭证 | 静态 token | 服务器只有**只读** deploy key |
| 传输 | HTTP 明文 | Git 平台 HTTPS |
| 推送认证 | token 即全部 | Git 平台账号（可 2FA、有审计日志） |
| 运行权限 | root | 后端 fbapp 低权用户，watcher 仅一条 sudo 白名单 |

## 一次性配置

### 1. 建私有仓库（GitHub / Gitee 均可）

仓库内容不需要初始化，`publish_v2.py` 会推 backend/ + dist/ 上去。
**`.env` 不进仓库**，首次安装时手动放到服务器。

### 2. 服务器（root 执行一次）

```bash
# 生成只读 deploy key，公钥配到仓库的 Deploy Keys（只读！）
ssh-keygen -t ed25519 -f /opt/futures-backtest_deploy_key -N ""
# 把私钥给 fbapp 用户用
mkdir -p /home/fbapp/.ssh 2>/dev/null || true

bash deploy_v2/install_v2.sh git@github.com:你的账号/futures-backtest.git
# 按提示把生产 .env 放到 /opt/futures-backtest/repo/backend/.env
```

### 3. 本地（一次性）

```bash
git clone <同一个仓库地址> .deploy/release-repo
cd .deploy/release-repo && git checkout -b release
```

### 4. 安全组

只需放行 8001（建议限 IP）。9000 永远关闭，5432 永不对公网。

## 日常发布

```bash
python publish_v2.py
```

推完最多 2 分钟内服务器自动部署。看进度：服务器上 `journalctl -u futures-watcher -f`。

## 回滚

watcher 健康检查失败会自动回滚。手动回滚：

```bash
ls -t /opt/futures-backtest/releases/ | head -5    # 找到上一个 sha
ln -sfn /opt/futures-backtest/releases/<上一个sha> /opt/futures-backtest/current
systemctl restart futures-backend
```

## 注意

- watcher 不执行仓库里任何脚本，只做 checkout + 拷贝 + 软链，即使仓库被污染也只能部署"代码本身"，不能借部署过程执行额外命令——后端的代码执行风险与 v1 相同（回测 exec），所以 8001 也务必限制访问
- deploy key 务必**只读**；泄露的最坏后果是代码被读，无法推送、无法登录服务器
