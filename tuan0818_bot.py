#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
0818tuan.com 优惠信息采集 + 企业微信机器人推送

用法：
  1. 修改 WEBHOOK_URL 为你的企业微信机器人地址
  2. python3 tuan0818_bot.py
  3. 定时运行（Linux/Mac）：crontab -e
     */30 * * * * cd /path/to/script && python3 tuan0818_bot.py >> cron.log 2>&1

依赖：pip install requests
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

# 企业微信机器人 Webhook（必填！）
# 建议通过环境变量设置：export WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key粘贴到这里"
)

# 采集配置
BASE_URL = "http://www.0818tuan.com"
LIST_URL_TEMPLATE = "http://www.0818tuan.com/list-1-{page}.html"
DETAIL_URL_TEMPLATE = "http://www.0818tuan.com/xbhd/{post_id}.html"

# 只采集前 N 页（每页约20-30条，0=最新页）
MAX_PAGES = 2

# 每次最多推送 N 条（避免刷屏）
MAX_PUSH_COUNT = 10

# 去重记录文件
HISTORY_FILE = "tuan0818_history.json"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "http://www.0818tuan.com/",
}

# 日志配置
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
    """发送纯文本消息"""
    data = {
        "msgtype": "text",
        "text": {
            "content": content,
            "mentioned_list": mentioned_list or [],
        },
    }
    return _post(data)


def send_markdown(content: str) -> bool:
    """发送 Markdown 消息"""
    data = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }
    return _post(data)


def send_news(title: str, description: str, url: str, pic_url: str = "") -> bool:
    """发送图文卡片（最推荐，可点击跳转）"""
    data = {
        "msgtype": "news",
        "news": {
            "articles": [
                {
                    "title": title,
                    "description": description,
                    "url": url,
                    "picurl": pic_url,
                }
            ]
        },
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
    """
    采集列表页，返回 [{post_id, title, url}, ...]
    """
    url = LIST_URL_TEMPLATE.format(page=page)
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            logger.warning(f"列表页 {page} 状态码异常: {resp.status_code}")
            return items

        # 正则提取：ID + 标题
        # 匹配格式如：xbhd/2207757.html" target="_blank" title="补贴 页面..."
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

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 列表页 {page} 请求失败: {e}")
        return items
    except Exception as e:
        logger.error(f"❌ 列表页 {page} 异常: {e}")
        return items


def fetch_detail(post_id: str) -> Optional[Dict]:
    """
    采集详情页，返回完整内容
    """
    url = DETAIL_URL_TEMPLATE.format(post_id=post_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return None

        text = resp.text

        # 提取标题（h1 标签）
        title_match = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S)
        title = title_match.group(1).strip() if title_match else ""
        title = re.sub(r'<[^>]+>', '', title).strip()

        # 提取发布时间
        time_match = re.search(
            r'时间[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
            text
        )
        pub_time = time_match.group(1) if time_match else ""

        # 提取正文内容
        content = ""
        content_match = re.search(r'<article[^>]*>(.*?)</article>', text, re.S)
        if not content_match:
            content_match = re.search(
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                text, re.S
            )
        if content_match:
            raw_html = content_match.group(1)
            # 去掉 script/style
            raw_html = re.sub(r'<script.*?</script>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<style.*?</style>', '', raw_html, flags=re.S)
            # 转换换行
            raw_html = re.sub(r'<br\s*/?>', '\n', raw_html, flags=re.S)
            raw_html = re.sub(r'<p>', '\n', raw_html, flags=re.S)
            raw_html = re.sub(r'</p>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<[^>]+>', '', raw_html, flags=re.S)
            content = raw_html.strip()
            content = re.sub(r'\n{3,}', '\n\n', content)

        # 如果没提取到内容，用标题兜底
        if not content:
            content = title

        # 提取第一张图片作为封面
        pic_url = ""
        img_match = re.search(r'<img[^>]+src="(https?://[^"]+)"', text)
        if img_match:
            pic_url = img_match.group(1)

        return {
            "post_id": post_id,
            "title": title,
            "url": url,
            "pub_time": pub_time,
            "content": content,
            "pic_url": pic_url,
        }

    except Exception as e:
        logger.error(f"❌ 详情页 {post_id} 异常: {e}")
        return None


# ==================== 去重管理 ====================

def load_history() -> set:
    """加载已推送的记录"""
    if not os.path.exists(HISTORY_FILE):
        return set()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("pushed_ids", []))
    except Exception:
        return set()


def save_history(pushed_ids: set):
    """保存已推送记录"""
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

    # 1. 加载历史记录
    history = load_history()
    logger.info(f"📚 历史记录: {len(history)} 条")

    # 2. 采集列表
    all_items = []
    for page in range(MAX_PAGES):
        items = fetch_list_page(page)
        if not items:
            break
        all_items.extend(items)
        time.sleep(1)  # 礼貌间隔

    if not all_items:
        logger.warning("⚠️ 未采集到任何数据，任务结束")
        return

    logger.info(f"📦 总计采集 {len(all_items)} 条列表数据")

    # 3. 去重，筛选新内容
    new_items = [item for item in all_items if item["post_id"] not in history]
    if not new_items:
        logger.info("✅ 没有新内容，无需推送")
        return

    logger.info(f"🆕 发现 {len(new_items)} 条新内容")

    # 4. 取最新 N 条进行详情采集和推送
    new_items = new_items[:MAX_PUSH_COUNT]

    pushed_count = 0
    for item in new_items:
        post_id = item["post_id"]

        # 采集详情
        detail = fetch_detail(post_id)
        if not detail:
            # 详情失败，用列表页信息兜底推送
            detail = {
                "post_id": post_id,
                "title": item["title"],
                "url": item["url"],
                "pub_time": "",
                "content": item["title"],
                "pic_url": "",
            }

        # 组装推送内容
        title = detail["title"] or item["title"]
        # 描述取前 200 字
        desc = detail["content"][:200].replace("\n", " ").strip()
        if len(detail["content"]) > 200:
            desc += "..."

        # 添加时间前缀
        if detail["pub_time"]:
            title = f"[{detail['pub_time'][5:16]}] {title}"

        # 推送图文卡片
        success = send_news(
            title=title,
            description=desc,
            url=detail["url"],
            pic_url=detail.get("pic_url", ""),
        )

        if success:
            history.add(post_id)
            pushed_count += 1

        time.sleep(1.5)  # 避免触发频率限制

    # 5. 保存历史
    save_history(history)

    # 6. 发送汇总
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
