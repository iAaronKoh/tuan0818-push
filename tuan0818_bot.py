#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
0818tuan.com 优惠信息采集 + 企业微信机器人推送（直接显示内容版）

用法：
  1. export WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  2. python3 tuan0818_bot.py

定时：GitHub Actions cron '*/10 * * * *'
"""

import os
import re
import json
import time
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional

# ==================== 配置区 ====================

WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key粘贴到这里"
)

BASE_URL = "http://www.0818tuan.com"
LIST_URL_TEMPLATE = "http://www.0818tuan.com/list-1-{page}.html"
DETAIL_URL_TEMPLATE = "http://www.0818tuan.com/xbhd/{post_id}.html"

MAX_PAGES = 2          # 采集页数
MAX_PUSH_COUNT = 10    # 每次最多推送条数
HISTORY_FILE = "tuan0818_history.json"

# 企业微信 Markdown 单条最大 4096 字节，留点余量
MAX_CONTENT_LENGTH = 3500

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "http://www.0818tuan.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("tuan0818_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ==================== 企业微信推送函数 ====================

def send_text(content: str, mentioned_list: Optional[List[str]] = None) -> bool:
    """发送纯文本消息（用于汇总）"""
    data = {
        "msgtype": "text",
        "text": {
            "content": content,
            "mentioned_list": mentioned_list or [],
        },
    }
    return _post(data)


def send_markdown(content: str) -> bool:
    """
    发送 Markdown 消息（直接显示内容）
    企业微信支持的语法：标题、加粗、斜体、链接、引用、代码、颜色(green/gray/orange)
    """
    data = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }
    return _post(data)


def _post(data: Dict) -> bool:
    """底层 POST 发送"""
    try:
        resp = requests.post(
            WEBHOOK_URL,
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info(f"✅ 推送成功 [{data.get('msgtype')}]")
            return True
        else:
            logger.error(f"❌ 推送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"❌ 网络异常: {e}")
        return False


# ==================== 采集函数 ====================

def fetch_list_page(page: int) -> List[Dict]:
    """采集列表页"""
    url = LIST_URL_TEMPLATE.format(page=page)
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            logger.warning(f"列表页 {page} 状态码异常: {resp.status_code}")
            return items

        pattern = r'[d\/](\d{7,})\.html" target="_blank" title="([\u4e00-\u9fa5][^"]*)"'
        matches = re.findall(pattern, resp.text)

        for post_id, title in matches:
            items.append({
                "post_id": post_id,
                "title": title.strip(),
                "url": DETAIL_URL_TEMPLATE.format(post_id=post_id),
            })

        logger.info(f"📄 列表页 {page} 采集到 {len(items)} 条")
        return items

    except Exception as e:
        logger.error(f"❌ 列表页 {page} 异常: {e}")
        return items


def fetch_detail(post_id: str) -> Optional[Dict]:
    """采集详情页"""
    url = DETAIL_URL_TEMPLATE.format(post_id=post_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return None

        text = resp.text

        # 提取标题
        title_match = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S)
        title = title_match.group(1).strip() if title_match else ""
        title = re.sub(r'<[^>]+>', '', title).strip()

        # 提取发布时间
        time_match = re.search(
            r'时间[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
            text
        )
        pub_time = time_match.group(1) if time_match else ""

        # 提取正文
        content = ""
        content_match = re.search(r'<article[^>]*>(.*?)</article>', text, re.S)
        if not content_match:
            content_match = re.search(
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                text, re.S
            )
        if content_match:
            raw_html = content_match.group(1)
            raw_html = re.sub(r'<script.*?</script>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<style.*?</style>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<br\s*/?>', '\n', raw_html, flags=re.S)
            raw_html = re.sub(r'<p>', '\n', raw_html, flags=re.S)
            raw_html = re.sub(r'</p>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<[^>]+>', '', raw_html, flags=re.S)
            content = raw_html.strip()
            content = re.sub(r'\n{3,}', '\n\n', content)

        if not content:
            content = title

        return {
            "post_id": post_id,
            "title": title,
            "url": url,
            "pub_time": pub_time,
            "content": content,
        }

    except Exception as e:
        logger.error(f"❌ 详情页 {post_id} 异常: {e}")
        return None


# ==================== 去重管理 ====================

def load_history() -> set:
    if not os.path.exists(HISTORY_FILE):
        return set()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("pushed_ids", []))
    except Exception:
        return set()


def save_history(pushed_ids: set):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "pushed_ids": list(pushed_ids),
                    "updated_at": datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logger.error(f"保存历史记录失败: {e}")


# ==================== 主流程 ====================

def main():
    logger.info("🚀 0818tuan 采集推送任务启动")

    history = load_history()
    logger.info(f"📚 历史记录: {len(history)} 条")

    # 采集列表
    all_items = []
    for page in range(MAX_PAGES):
        items = fetch_list_page(page)
        if not items:
            break
        all_items.extend(items)
        time.sleep(1)

    if not all_items:
        logger.warning("⚠️ 未采集到任何数据，任务结束")
        return

    logger.info(f"📦 总计采集 {len(all_items)} 条列表数据")

    # 去重
    new_items = [item for item in all_items if item["post_id"] not in history]
    if not new_items:
        logger.info("✅ 没有新内容，无需推送")
        return

    logger.info(f"🆕 发现 {len(new_items)} 条新内容")
    new_items = new_items[:MAX_PUSH_COUNT]

    pushed_count = 0
    for item in new_items:
        post_id = item["post_id"]

        # 采集详情
        detail = fetch_detail(post_id)
        if not detail:
            detail = {
                "post_id": post_id,
                "title": item["title"],
                "url": item["url"],
                "pub_time": "",
                "content": item["title"],
            }

        title = detail["title"] or item["title"]
        pub_time = detail["pub_time"]
        content = detail["content"]
        url = detail["url"]

        # 组装 Markdown 内容（直接显示）
        md_lines = []

        # 标题
        md_lines.append(f"**🎁 {title}**")
        md_lines.append("")

        # 发布时间
        if pub_time:
            md_lines.append(f"<font color='gray'>⏰ {pub_time}</font>")
            md_lines.append("")

        # 正文内容
        # 清理多余空行，保留换行
        content_clean = content.strip()
        # 企业微信 Markdown 中，换行需要双换行才能显示为段落分隔
        # 但为了紧凑，我们用单换行 + 引用格式

        # 如果内容太长，截断
        if len(content_clean.encode('utf-8')) > MAX_CONTENT_LENGTH:
            # 按字节截断，避免截断到半个汉字
            truncated = content_clean.encode('utf-8')[:MAX_CONTENT_LENGTH].decode('utf-8', errors='ignore')
            content_clean = truncated + "\n\n...（内容过长，已截断）"

        md_lines.append(content_clean)
        md_lines.append("")

        # 原文链接
        md_lines.append(f"<font color='info'>🔗 [查看原文]({url})</font>")

        # 分隔线
        md_lines.append("---")

        markdown_content = "\n".join(md_lines)

        # 推送 Markdown（直接显示内容）
        success = send_markdown(markdown_content)

        if success:
            history.add(post_id)
            pushed_count += 1

        time.sleep(1.5)  # 避免频率限制

    # 保存历史
    save_history(history)

    # 发送汇总
    if pushed_count > 0:
        summary = (
            f"📢 0818tuan 推送完成\n"
            f"本次推送: {pushed_count} 条\n"
            f"累计记录: {len(history)} 条"
        )
        send_text(summary)
        logger.info(f"🎉 任务完成，推送 {pushed_count} 条")
    else:
        logger.warning("⚠️ 推送全部失败，请检查网络或 Webhook 配置")


if __name__ == "__main__":
    main()
