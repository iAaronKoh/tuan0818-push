# 0818tuan 优惠信息自动推送

自动采集 [0818tuan.com](http://www.0818tuan.com/) 最新优惠信息，推送到企业微信群。

## 部署方式

使用 GitHub Actions 定时运行，无需服务器。

## 文件说明

| 文件 | 说明 |
|------|------|
| `tuan0818_bot.py` | 主脚本：采集 + 推送 |
| `requirements.txt` | Python 依赖 |
| `.github/workflows/tuan0818.yml` | GitHub Actions 定时任务配置 |

## 快速开始

1. Fork 或新建仓库，上传这三个文件
2. 在仓库 Settings → Secrets → Actions 中添加 `WEBHOOK_URL`
3. 手动触发 Actions 测试
4. 坐等自动推送

详见完整部署教程。
