#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
0818tuan.com 优惠信息采集 + 企业微信机器人推送
修复：支持单引号href + 精确过滤垃圾<p>标签

用法：
  export WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  python3 tuan0818_bot.py

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

MAX_PAGES = 2
MAX_PUSH_COUNT = 10
HISTORY_FILE = "tuan0818_history.json"
MAX_TEXT_BYTES = 1900

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
    data = {
        "msgtype": "text",
        "text": {
            "content": content,
            "mentioned_list": mentioned_list or [],
        },
    }
    return _post(data)


def _post(data: Dict) -> bool:
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

        # ========== 提取正文（基于真实HTML结构） ==========
        content = ""

        # 策略1：匹配 <div class="post-content" id="xbcontent"> 的内容
        # 源码中这个div后面是 <!-- 评论 开始 -->，用这个作为结束锚点
        content_match = re.search(
            r'<div[^>]*class="post-content"[^>]*>(.*?)</div>\s*<!-- 评论',
            text, re.S
        )
        if not content_match:
            # 兜底：匹配 article 或 content div
            content_match = re.search(r'<article[^>]*>(.*?)</article>', text, re.S)
        if not content_match:
            content_match = re.search(
                r'<div[^>]*class="[^"]*(?:content|post|entry)[^"]*"[^>]*>(.*?)</div>',
                text, re.S
            )

        if content_match:
            raw_html = content_match.group(1)

            # ========== 第1步：先提取所有链接（支持单引号和双引号）==========
            # 源码中：href='https://kzurl18.cn/t8ZrHC' 是单引号！
            def replace_link(m):
                href = m.group(1).strip()
                link_text = m.group(2).strip()
                href = href.replace('&amp;', '&')
                # 如果链接文本就是链接本身，直接返回链接
                if link_text == href or (len(link_text) < 5 and href.startswith('http')):
                    return href
                return f"{link_text}({href})"

            # 关键修复：href=[\'\"] 同时支持单引号和双引号
            raw_html = re.sub(
                r'<a\s+[^>]*href=[\'\"]([^\'\"]+)[\'\"][^>]*>(.*?)</a>',
                replace_link,
                raw_html,
                flags=re.S | re.I
            )

            # ========== 第2步：去掉 script/style/iframe/noscript ==========
            raw_html = re.sub(r'<script.*?</script>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<style.*?</style>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<iframe.*?</iframe>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<noscript.*?</noscript>', '', raw_html, flags=re.S)

            # ========== 第3步：过滤垃圾 <p> 标签（精确匹配）==========
            # 源码中垃圾内容在普通 <p> 标签里，没有特定 class
            # 通过内容关键词判断，删除整个 <p>...</p>
            trash_keywords = [
                '加入收藏', '上一篇', '下一篇', '上一条', '下一条',
                '你可能还喜欢', '相关推荐', '热门推荐', '猜你喜欢',
                'pageLink', '发表评论', '评论列表', '最新评论',
            ]

            def filter_p(m):
                p_html = m.group(0)  # 整个 <p>...</p>
                p_text = re.sub(r'<[^>]+>', '', p_html)  # 去掉标签看纯文本
                for kw in trash_keywords:
                    if kw in p_text or kw in p_html:
                        return ''  # 删除整个 <p>
                return p_html  # 保留

            # 匹配 <p>...</p>（非贪婪，不跨标签）
            raw_html = re.sub(r'<p[^>]*>.*?</p>', filter_p, raw_html, flags=re.S | re.I)

            # ========== 第4步：转换剩余 HTML 标签为文本 ==========
            raw_html = re.sub(r'<br\s*/?>', '\n', raw_html, flags=re.S)
            raw_html = re.sub(r'<p[^>]*>', '\n', raw_html, flags=re.S)
            raw_html = re.sub(r'</p>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<div[^>]*>', '\n', raw_html, flags=re.S)
            raw_html = re.sub(r'</div>', '', raw_html, flags=re.S)
            raw_html = re.sub(r'<li>', '\n• ', raw_html, flags=re.S)
            raw_html = re.sub(r'</li>', '', raw_html, flags=re.S)
            # 去掉所有剩余标签（此时 <a> 已经处理过了）
            raw_html = re.sub(r'<[^>]+>', '', raw_html, flags=re.S)

            # ========== 第5步：处理 HTML 实体 ==========
            raw_html = raw_html.replace('&nbsp;', ' ')
            raw_html = raw_html.replace('&quot;', '"')
            raw_html = raw_html.replace('&amp;', '&')
            raw_html = raw_html.replace('&lt;', '<')
            raw_html = raw_html.replace('&gt;', '>')
            raw_html = raw_html.replace('&#160;', ' ')
            raw_html = raw_html.replace('&ensp;', ' ')
            raw_html = raw_html.replace('&emsp;', ' ')
            raw_html = raw_html.replace('&copy;', '©')
            raw_html = raw_html.replace('&reg;', '®')
            raw_html = raw_html.replace('&trade;', '™')

            content = raw_html.strip()

        # 兜底
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

    new_items = [item for item in all_items if item["post_id"] not in history]
    if not new_items:
        logger.info("✅ 没有新内容，无需推送")
        return

    logger.info(f"🆕 发现 {len(new_items)} 条新内容")
    new_items = new_items[:MAX_PUSH_COUNT]

    pushed_count = 0
    for item in new_items:
        post_id = item["post_id"]

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

        # 组装纯文本
        lines = []
        lines.append(f"【{title}】")
        lines.append("")

        if pub_time:
            lines.append(f"⏰ {pub_time}")
            lines.append("")

        lines.append(content)
        lines.append("")

        full_text = "\n".join(lines)

        # 超长截断
        text_bytes = full_text.encode('utf-8')
        if len(text_bytes) > MAX_TEXT_BYTES:
            truncated = text_bytes[:MAX_TEXT_BYTES].decode('utf-8', errors='ignore')
            truncated = truncated.rsplit('\n', 1)[0]
            full_text = truncated + "\n\n...（内容过长，点击查看原文）\n" + url

        success = send_text(full_text)

        if success:
            history.add(post_id)
            pushed_count += 1

        time.sleep(1.5)

    save_history(history)

    if pushed_count > 0:
        summary = (
            f"📢 你好,KOH 信息推送完成\n"
            f"本次推送: {pushed_count} 条\n"
            f"累计记录: {len(history)} 条"
        )
        send_text(summary)
        logger.info(f"🎉 任务完成，推送 {pushed_count} 条")
    else:
        logger.warning("⚠️ 推送全部失败，请检查网络或 Webhook 配置")


if __name__ == "__main__":
    main()
