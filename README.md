# DeepSeek GitHub Monitor

监控 deepseek-ai GitHub 组织，当有新仓库、新 release 或新 tag 时，通过飞书机器人发送通知。

## 功能

- 监控新仓库创建
- 监控新版本发布
- 监控新标签创建
- 特别关注 v3 和 r2 相关版本（标题会明确标注）
- 通过 GitHub Actions 定时执行（每 30 分钟）

## 配置

在 GitHub 仓库设置中添加以下 Secrets：

- `FEISHU_WEBHOOK_URL`: 飞书自定义机器人 Webhook URL

## 本地测试

```bash
pip install -r requirements.txt
export FEISHU_WEBHOOK_URL="your_webhook_url"
python monitor.py
```

## GitHub Actions

工作流会自动运行，也可以在 Actions 页面手动触发。

状态文件会保存在 GitHub Artifacts 中，确保每次运行能检测到变化。
