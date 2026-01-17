#!/usr/bin/env python3
"""
McDonald's MCP Auto Claim Script
自动查询活动日历、领取优惠券并推送到Telegram
支持 GitHub Actions 调度和 GitHub Pages 部署
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# MCP配置
MCP_URL = "https://mcp.mcd.cn/mcp-servers/mcd-mcp"
TOKEN = os.getenv("MCD_TOKEN", "")

# Telegram配置
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# GitHub Pages 配置
GITHUB_PAGES_URL = os.getenv("GITHUB_PAGES_URL", "")

# 数据文件路径
CALENDAR_DATA_FILE = "calendar_data.json"


def call_mcp(token, method, params, session_id=None):
    """调用MCP API"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            new_session = resp.headers.get("Mcp-Session-Id")
            body = resp.read().decode("utf-8")
            return json.loads(body), new_session or session_id
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return {"error": {"message": f"HTTP {exc.code}: {body}"}}, session_id
    except Exception as exc:
        return {"error": {"message": str(exc)}}, session_id


def initialize_session():
    """初始化MCP会话"""
    init_payload = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "clientInfo": {"name": "mcd-auto-claim", "version": "1.0.0"},
    }

    init_resp, session_id = call_mcp(TOKEN, "initialize", init_payload)
    if init_resp.get("error"):
        return None, False
    return session_id, True


def call_tool(tool_name, session_id, arguments=None):
    """调用MCP工具"""
    payload_args = arguments or {}
    resp, _ = call_mcp(
        TOKEN,
        "tools/call",
        {"name": tool_name, "arguments": payload_args},
        session_id=session_id,
    )
    return resp


def get_now_time(session_id):
    """获取MCP服务器时间"""
    return call_tool("now-time-info", session_id)


def get_calendar(session_id):
    """获取活动日历"""
    return call_tool("campaign-calender", session_id)


def get_my_coupons(session_id):
    """获取我的优惠券"""
    return call_tool("my-coupons", session_id)


def auto_claim_coupons(session_id):
    """自动领取优惠券"""
    return call_tool("auto-bind-coupons", session_id)


def parse_calendar_activities(text, server_date=None):
    """解析日历活动文本,提取当月活动并过滤过期活动,包含详细信息"""
    if not text:
        return []
    
    # 使用服务器时间或本地时间
    if server_date:
        current_date = datetime.strptime(server_date, "%Y-%m-%d")
    else:
        current_date = datetime.now()
    
    current_month = current_date.month
    current_year = current_date.year
    
    activities = []
    # 匹配日期格式: #### 2026年1月17日 或 #### 1月17日
    date_pattern = r'####?\s*(?:(\d+)年)?(\d+)月(\d+)日'
    
    matches = list(re.finditer(date_pattern, text))
    for i, match in enumerate(matches):
        year = int(match.group(1)) if match.group(1) else current_year
        month = int(match.group(2))
        day = int(match.group(3))
        
        # 只处理当月活动
        if month != current_month or year != current_year:
            continue
        
        # 过滤已过期的活动(在服务器日期之前的)
        activity_date = datetime(year, month, day)
        if activity_date < current_date.replace(hour=0, minute=0, second=0, microsecond=0):
            continue
        
        # 提取该日期的活动内容
        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start_pos:end_pos].strip()
        
        # 提取活动详情 (标题、内容、图片)
        activity_list = parse_activity_details(content)
        
        if activity_list:
            activities.append({
                "date": f"{year}-{month:02d}-{day:02d}",
                "count": len(activity_list),
                "activities": activity_list  # 包含详细活动信息
            })
    
    return activities


def parse_activity_details(content):
    """解析活动详情,提取标题、内容介绍和图片"""
    activities = []
    
    # 按活动块分割 - 每个活动以 "- **活动标题**" 开始
    # 首先标准化换行符
    content = content.replace('\\n', '\n').replace('\\\\n', '\n')
    
    # 按活动块分割
    activity_blocks = re.split(r'\n-\s*\*\*活动标题\*\*', content)
    
    for i, block in enumerate(activity_blocks):
        if not block.strip():
            continue
        
        # 第一个块可能直接以 **活动标题** 开始
        if i == 0 and '**活动标题**' not in block:
            # 检查是否有标题在块开头
            if block.strip().startswith('**活动标题**'):
                block = block.strip()[len('**活动标题**'):]
            else:
                continue
        
        # 提取标题
        title_match = re.search(r'^[：:]\s*(.+?)(?:\n|$)', block)
        if not title_match:
            # 尝试从块开头提取
            title_match = re.search(r'^\s*(.+?)(?:\n|$)', block)
        
        title = title_match.group(1).strip() if title_match else ""
        title = clean_text(title)
        
        # 提取内容介绍
        content_match = re.search(r'\*\*活动内容介绍\*\*[：:]\s*([\s\S]*?)(?=\*\*活动图片介绍\*\*|$)', block)
        intro = content_match.group(1).strip() if content_match else ""
        intro = clean_text(intro)
        # 限制内容长度
        if len(intro) > 300:
            intro = intro[:300] + "..."
        
        # 提取图片
        img_match = re.search(r'<img\s+src="([^"]+)"', block)
        img = img_match.group(1) if img_match else ""
        
        if title:
            activities.append({
                "title": title,
                "content": intro,
                "img": img
            })
    
    # 如果上面没有解析到，尝试更简单的方式
    if not activities:
        # 匹配所有标题
        title_matches = re.finditer(r'\*\*活动标题\*\*[：:]\s*(.+?)(?:\n|\\n|$)', content)
        img_matches = list(re.finditer(r'<img\s+src="([^"]+)"', content))
        
        for idx, match in enumerate(title_matches):
            title = clean_text(match.group(1).strip())
            img = img_matches[idx].group(1) if idx < len(img_matches) else ""
            if title:
                activities.append({
                    "title": title,
                    "content": "",
                    "img": img
                })
    
    return activities


def clean_text(text):
    """清理文本中的转义字符和多余空白"""
    if not text:
        return ""
    # 清理转义字符
    text = text.replace('\\n', '\n')
    text = text.replace('\\\\', '')
    text = text.replace('\\ ', ' ')
    # 清理多余空白
    text = re.sub(r'\n\s*\n', '\n', text)
    text = text.strip()
    return text


def parse_claim_result(text):
    """解析领券结果"""
    if not text:
        return {"success": 0, "failed": 0, "coupons": [], "message": ""}
    
    # 检查是否有错误信息
    if "领券失败" in text or "暂无可领取" in text:
        return {"success": 0, "failed": 0, "coupons": [], "message": "暂无可领取的优惠券"}
    
    # 提取成功和失败数量
    success_match = re.search(r'成功[：:]\s*(\d+)', text)
    fail_match = re.search(r'失败[：:]\s*(\d+)', text)
    
    success = int(success_match.group(1)) if success_match else 0
    failed = int(fail_match.group(1)) if fail_match else 0
    
    # 提取优惠券标题
    coupon_pattern = r'\*\*(.+?)\*\*'
    coupons = re.findall(coupon_pattern, text)
    
    return {
        "success": success,
        "failed": failed,
        "coupons": coupons[:success] if coupons else [],
        "message": ""
    }


def parse_my_coupons(text):
    """解析我的优惠券详细信息"""
    if not text:
        return []
    
    coupons = []
    # 匹配优惠券详情: ## 标题 ... **优惠**: ¥价格 ... **有效期**: 日期 ... <img src="...">
    # 分段匹配以包含图片
    sections = re.split(r'(?=##\s+[^\n]+)', text)
    
    for section in sections:
        if not section.strip():
            continue
        
        # 提取标题
        title_match = re.search(r'##\s*(.+?)[\n\r]', section)
        if not title_match:
            continue
        title = title_match.group(1).strip()
        
        # 提取价格
        price_match = re.search(r'\*\*优惠\*\*[：:]\s*¥?(\d+(?:\.\d+)?)', section)
        price = price_match.group(1).strip() if price_match else "0"
        
        # 提取有效期
        validity_match = re.search(r'\*\*有效期\*\*[：:]\s*([^\n]+)', section)
        validity = validity_match.group(1).strip() if validity_match else "未知"
        
        # 提取图片链接
        img_match = re.search(r'<img\s+src="([^"]+)"', section)
        img = img_match.group(1) if img_match else ""
        
        coupons.append({
            "title": title,
            "price": price,
            "validity": validity,
            "img": img
        })
    
    return coupons


def send_telegram_message(message):
    """发送Telegram消息"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured, skipping push")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception as e:
        print(f"Telegram push failed: {e}")
        return False


def format_report(calendar_data, claim_result, my_coupons, pages_url=None):
    """格式化Telegram报告 - 简洁版"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    report = f"🍔 *麦当劳优惠券自动领取报告*\n"
    report += f"⏰ `{now}`\n\n"
    
    # 统计概览
    total_activities = sum(a['count'] for a in calendar_data) if calendar_data else 0
    report += f"📊 *数据概览*\n"
    report += f"• 本月活动: {total_activities} 个\n"
    report += f"• 可用优惠券: {len(my_coupons)} 张\n"
    if claim_result.get('message'):
        report += f"• {claim_result['message']}\n"
    else:
        report += f"• 新领取: {claim_result['success']} 张\n"
    report += f"\n"
    
    # 活动详情 - 显示活动标题（简化版）
    if calendar_data:
        report += f"📅 *近期活动*\n"
        for day_data in calendar_data[:3]:
            date = day_data['date']
            activities = day_data.get('activities', [])
            report += f"\n*{date}* ({len(activities)}个)\n"
            for act in activities[:3]:
                title = act.get('title', '')[:30]
                if len(act.get('title', '')) > 30:
                    title += "..."
                report += f"  • {title}\n"
            if len(activities) > 3:
                report += f"  • ...还有{len(activities)-3}个\n"
        if len(calendar_data) > 3:
            report += f"\n📌 还有{len(calendar_data)-3}天有活动\n"
        report += "\n"
    
    # 我的优惠券 - 按价格分类（简化版，不重复日期表情）
    if my_coupons:
        report += f"🎟️ *我的优惠券* ({len(my_coupons)}张)\n\n"
        
        # 按价格排序分组
        sorted_coupons = sorted(my_coupons, key=lambda x: float(x['price']))
        
        # 10元以下
        cheap = [c for c in sorted_coupons if float(c['price']) < 10]
        # 10-20元
        medium = [c for c in sorted_coupons if 10 <= float(c['price']) < 20]
        # 20元以上
        expensive = [c for c in sorted_coupons if float(c['price']) >= 20]
        
        if cheap:
            report += f"💵 *超值优惠 (<10元)*\n"
            for c in cheap:
                validity = parse_validity_short(c.get('validity', ''))
                report += f"• ¥{float(c['price']):.1f} {c['title']} ({validity})\n"
            report += f"\n"
        
        if medium:
            report += f"💰 *实惠套餐 (10-20元)*\n"
            for c in medium:
                validity = parse_validity_short(c.get('validity', ''))
                report += f"• ¥{float(c['price']):.1f} {c['title']} ({validity})\n"
            report += f"\n"
        
        if expensive:
            report += f"🌟 *豪华组合 (>20元)*\n"
            for c in expensive:
                validity = parse_validity_short(c.get('validity', ''))
                report += f"• ¥{float(c['price']):.1f} {c['title']} ({validity})\n"
    else:
        report += f"🎟️ 暂无可用优惠券\n"
    
    # 添加 GitHub Pages 链接
    if pages_url:
        report += f"\n🔗 [查看详情]({pages_url})\n"
    
    return report


def parse_validity_short(validity):
    """解析有效期，返回简短格式"""
    if not validity or validity == "未知":
        return "有效期未知"
    
    # 提取日期范围
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})\s*[\d:]*\s*-\s*(\d{4}-\d{2}-\d{2})', validity)
    if date_match:
        start = date_match.group(1)
        end = date_match.group(2)
        # 只显示月-日
        start_short = start[5:]  # MM-DD
        end_short = end[5:]
        return f"{start_short} 至 {end_short}"
    
    return validity[:20] if len(validity) > 20 else validity


def generate_html_report(calendar_data, claim_result, my_coupons):
    """生成HTML报告 - 优化版，包含详细活动信息和完整有效期"""
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # 生成优惠券HTML - 显示完整有效期（开始-结束时间）
    coupons_html = ""
    if my_coupons:
        for c in my_coupons:
            img_tag = f'<img src="{c["img"]}" class="coupon-img" alt="{c["title"]}" onerror="this.style.display=\'none\'">' if c.get('img') else ''
            # 解析有效期，显示开始和结束时间
            validity_display = format_validity_display(c.get('validity', ''))
            coupons_html += f"""
            <div class="coupon-card">
                <div class="coupon-img-wrapper">
                    {img_tag}
                    <div class="coupon-price-badge">¥{c['price']}</div>
                </div>
                <div class="coupon-info">
                    <div class="coupon-title">{c['title']}</div>
                    <div class="coupon-validity">
                        {validity_display}
                    </div>
                </div>
            </div>
            """
    else:
        coupons_html = '<div class="no-data">暂无可用优惠券</div>'
    
    # 生成活动日历HTML - 显示详细活动信息
    activities_html = generate_activities_html(calendar_data)
    
    # 计算总活动数
    total_activities = sum(a['count'] for a in calendar_data) if calendar_data else 0
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🍔 麦当劳优惠券报告 - {now.strftime("%Y-%m-%d")}</title>
    <style>
        :root {{
            --mcd-yellow: #FFC72C;
            --mcd-red: #DA291C;
            --bg-dark: #1a1a2e;
            --bg-card: #16213e;
            --text: #333;
            --text-muted: #666;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: linear-gradient(135deg, var(--bg-dark) 0%, #0f0f23 100%);
            min-height: 100vh;
            padding: 20px;
            color: var(--text);
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, var(--mcd-yellow) 0%, var(--mcd-red) 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
            border-radius: 20px 20px 0 0;
        }}
        .header h1 {{
            font-size: 2.2rem;
            margin-bottom: 10px;
        }}
        .header .time {{
            opacity: 0.9;
            font-size: 0.95rem;
        }}
        .content {{
            background: white;
            padding: 30px;
            border-radius: 0 0 20px 20px;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            color: var(--mcd-red);
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 3px solid var(--mcd-yellow);
            font-size: 1.5rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .section h2 .count {{
            background: var(--mcd-red);
            color: white;
            font-size: 0.9rem;
            padding: 4px 12px;
            border-radius: 20px;
        }}
        
        /* 活动日历样式 */
        .activity-day {{
            background: #f8f9fa;
            border-radius: 12px;
            margin-bottom: 16px;
            overflow: hidden;
            border: 2px solid #eee;
        }}
        .activity-day-header {{
            background: linear-gradient(135deg, var(--mcd-yellow) 0%, #ffdb58 100%);
            padding: 12px 20px;
            font-weight: bold;
            color: #333;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .activity-day-header:hover {{
            background: linear-gradient(135deg, #ffdb58 0%, var(--mcd-yellow) 100%);
        }}
        .activity-day-header .date {{
            font-size: 1.1rem;
        }}
        .activity-day-header .badge {{
            background: var(--mcd-red);
            color: white;
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 0.85rem;
        }}
        .activity-list {{
            padding: 0;
            list-style: none;
            display: none;
        }}
        .activity-list.show {{
            display: block;
        }}
        .activity-item {{
            padding: 16px 20px;
            border-bottom: 1px solid #eee;
            display: flex;
            gap: 16px;
            align-items: flex-start;
        }}
        .activity-item:last-child {{
            border-bottom: none;
        }}
        .activity-item img {{
            width: 80px;
            height: 80px;
            object-fit: cover;
            border-radius: 8px;
            flex-shrink: 0;
        }}
        .activity-item .info {{
            flex: 1;
        }}
        .activity-item .title {{
            font-weight: 600;
            color: #333;
            margin-bottom: 8px;
            font-size: 1rem;
        }}
        .activity-item .content {{
            color: #666;
            font-size: 0.9rem;
            line-height: 1.6;
        }}
        
        /* 领券结果样式 */
        .claim-result {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        .claim-card {{
            flex: 1;
            min-width: 150px;
            background: #f8f9fa;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }}
        .claim-card .num {{
            font-size: 2.5rem;
            font-weight: bold;
        }}
        .claim-card .num.success {{ color: #28a745; }}
        .claim-card .num.fail {{ color: #dc3545; }}
        .claim-card .label {{
            color: #666;
            margin-top: 8px;
        }}
        .claim-message {{
            padding: 20px;
            background: #fff3cd;
            border-radius: 12px;
            border-left: 4px solid #ffc107;
            color: #856404;
        }}
        
        /* 优惠券卡片样式 */
        .coupons-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
        }}
        .coupon-card {{
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            transition: transform 0.3s, box-shadow 0.3s;
            border: 2px solid var(--mcd-yellow);
        }}
        .coupon-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.15);
        }}
        .coupon-img-wrapper {{
            position: relative;
            height: 160px;
            background: linear-gradient(135deg, #f5f5f5 0%, #eee 100%);
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .coupon-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}
        .coupon-price-badge {{
            position: absolute;
            bottom: 10px;
            right: 10px;
            background: var(--mcd-red);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 1.2rem;
        }}
        .coupon-info {{
            padding: 16px;
        }}
        .coupon-title {{
            font-weight: 600;
            font-size: 1rem;
            color: #333;
            margin-bottom: 12px;
            min-height: 48px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        .coupon-validity {{
            font-size: 0.85rem;
            color: #666;
            padding-top: 12px;
            border-top: 2px dashed #eee;
        }}
        .validity-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .validity-row:last-child {{
            margin-bottom: 0;
        }}
        .validity-icon {{
            width: 16px;
            text-align: center;
        }}
        .validity-label {{
            color: #999;
            min-width: 50px;
        }}
        .validity-value {{
            color: #333;
            font-weight: 500;
        }}
        
        .no-data {{
            text-align: center;
            padding: 60px 20px;
            color: #999;
            font-size: 1.2rem;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: rgba(255,255,255,0.6);
            font-size: 0.9rem;
            margin-top: 20px;
        }}
        
        /* 展开/收起图标 */
        .toggle-icon {{
            transition: transform 0.3s;
        }}
        .toggle-icon.expanded {{
            transform: rotate(180deg);
        }}
        
        /* 活动图片样式 */
        .activity-item img {{
            width: 120px;
            height: 120px;
            object-fit: cover;
            border-radius: 12px;
            cursor: pointer;
            transition: transform 0.2s;
            border: 2px solid #eee;
        }}
        .activity-item img:hover {{
            transform: scale(1.05);
            border-color: var(--mcd-yellow);
        }}
        
        /* 图片放大模态框 */
        .image-modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .image-modal.show {{
            display: flex;
        }}
        .image-modal img {{
            max-width: 90%;
            max-height: 90%;
            object-fit: contain;
            border-radius: 12px;
        }}
        .image-modal-close {{
            position: absolute;
            top: 20px;
            right: 30px;
            color: white;
            font-size: 40px;
            cursor: pointer;
            z-index: 1001;
        }}
        .image-modal-close:hover {{
            color: var(--mcd-yellow);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🍔 麦当劳优惠券报告</h1>
            <div class="time">更新时间: {timestamp}</div>
        </div>
        
        <div class="content">
            <!-- 本月活动 -->
            <div class="section">
                <h2>📅 本月活动 <span class="count">{total_activities} 个活动</span></h2>
                {activities_html if calendar_data else '<div class="no-data">本月暂无活动</div>'}
            </div>
            
            <!-- 领券结果 -->
            <div class="section">
                <h2>🎁 领券结果</h2>
                {f'<div class="claim-message">{claim_result["message"]}</div>' if claim_result.get('message') else f'''
                <div class="claim-result">
                    <div class="claim-card">
                        <div class="num success">{claim_result['success']}</div>
                        <div class="label">成功领取</div>
                    </div>
                    <div class="claim-card">
                        <div class="num fail">{claim_result['failed']}</div>
                        <div class="label">领取失败</div>
                    </div>
                </div>
                '''}
            </div>
            
            <!-- 我的优惠券 -->
            <div class="section">
                <h2>🎟️ 我的优惠券 <span class="count">{len(my_coupons)} 张可用</span></h2>
                <div class="coupons-grid">
                    {coupons_html}
                </div>
            </div>
        </div>
        
        <div class="footer">
            由 GitHub Actions 自动生成 | Powered by MCD MCP
        </div>
    </div>
    
    <!-- 图片放大模态框 -->
    <div class="image-modal" id="imageModal" onclick="closeImageModal()">
        <span class="image-modal-close" onclick="closeImageModal()">&times;</span>
        <img id="modalImage" src="" alt="放大图片">
    </div>
    
    <script>
        // 点击展开/收起活动列表
        document.querySelectorAll('.activity-day-header').forEach(header => {{
            header.addEventListener('click', () => {{
                const list = header.nextElementSibling;
                const icon = header.querySelector('.toggle-icon');
                list.classList.toggle('show');
                icon.classList.toggle('expanded');
            }});
        }});
        
        // 默认展开第一个
        const firstHeader = document.querySelector('.activity-day-header');
        if (firstHeader) {{
            firstHeader.click();
        }}
        
        // 图片放大功能
        function showImageModal(src) {{
            const modal = document.getElementById('imageModal');
            const img = document.getElementById('modalImage');
            img.src = src;
            modal.classList.add('show');
            document.body.style.overflow = 'hidden';
        }}
        
        function closeImageModal() {{
            const modal = document.getElementById('imageModal');
            modal.classList.remove('show');
            document.body.style.overflow = '';
        }}
        
        // ESC 键关闭模态框
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                closeImageModal();
            }}
        }});
    </script>
</body>
</html>"""
    
    return html


def format_validity_display(validity):
    """格式化有效期显示，解析开始时间和结束时间"""
    if not validity or validity == "未知":
        return '<div class="validity-row"><span class="validity-icon">📅</span><span class="validity-value">有效期未知</span></div>'
    
    # 尝试解析格式: 2026-01-17 00:00-2026-01-18 23:59 周六、日 10:30-23:59 00:00-04:59
    # 或者: 2026-01-19 10:45-2026-01-23 23:59 周一、二、三、四、五 10:45-23:59
    
    html = ""
    
    # 提取日期范围
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})\s*[\d:]*\s*-\s*(\d{4}-\d{2}-\d{2})\s*[\d:]*', validity)
    if date_match:
        start_date = date_match.group(1)
        end_date = date_match.group(2)
        html += f'<div class="validity-row"><span class="validity-icon">📅</span><span class="validity-label">开始:</span><span class="validity-value">{start_date}</span></div>'
        html += f'<div class="validity-row"><span class="validity-icon">📅</span><span class="validity-label">结束:</span><span class="validity-value">{end_date}</span></div>'
    
    # 提取时间段
    time_match = re.search(r'(\d{2}:\d{2})-(\d{2}:\d{2})\s*(?:\d{2}:\d{2}-\d{2}:\d{2})?$', validity)
    if time_match:
        time_range = f"{time_match.group(1)}-{time_match.group(2)}"
        html += f'<div class="validity-row"><span class="validity-icon">⏰</span><span class="validity-label">时段:</span><span class="validity-value">{time_range}</span></div>'
    
    # 提取星期限制
    week_match = re.search(r'(周[一二三四五六日、]+)', validity)
    if week_match:
        html += f'<div class="validity-row"><span class="validity-icon">📆</span><span class="validity-label">限:</span><span class="validity-value">{week_match.group(1)}</span></div>'
    
    if not html:
        # 如果无法解析，直接显示原始有效期
        html = f'<div class="validity-row"><span class="validity-icon">📅</span><span class="validity-value">{validity}</span></div>'
    
    return html


def generate_activities_html(calendar_data):
    """生成活动日历HTML，包含详细活动信息，清理转义字符"""
    if not calendar_data:
        return ""
    
    html = ""
    for day_data in calendar_data:
        date = day_data['date']
        count = day_data['count']
        activities = day_data.get('activities', [])
        
        # 日期头部
        html += f'''
        <div class="activity-day">
            <div class="activity-day-header">
                <span class="date">{date}</span>
                <span>
                    <span class="badge">{count} 个活动</span>
                    <span class="toggle-icon">▼</span>
                </span>
            </div>
            <ul class="activity-list">
        '''
        
        # 活动列表
        for activity in activities:
            title = html_escape(clean_display_text(activity.get('title', '')))
            content = html_escape(clean_display_text(activity.get('content', '')))
            img = activity.get('img', '')
            
            # 图片带点击放大功能
            img_html = f'<img src="{img}" alt="{title}" class="activity-img" onclick="showImageModal(this.src)" onerror="this.style.display=\'none\'">' if img else ''
            content_html = f'<div class="content">{content}</div>' if content else ''
            
            html += f'''
                <li class="activity-item">
                    {img_html}
                    <div class="info">
                        <div class="title">{title}</div>
                        {content_html}
                    </div>
                </li>
            '''
        
        # 如果没有详细活动信息，显示简单提示
        if not activities:
            html += '<li class="activity-item"><div class="info"><div class="title">暂无详细信息</div></div></li>'
        
        html += '''
            </ul>
        </div>
        '''
    
    return html


def clean_display_text(text):
    """清理用于显示的文本，移除转义字符"""
    if not text:
        return ""
    # 移除各种转义字符
    text = text.replace('\\n', ' ')
    text = text.replace('\\\\n', ' ')
    text = text.replace('\\\\', '')
    text = text.replace('\\ ', ' ')
    text = text.replace('**活动图片介绍**：', '')
    text = text.replace('**活动图片介绍**:', '')
    # 移除多余空格
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text


def html_escape(text):
    """HTML转义"""
    if not text:
        return ""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text


def save_calendar_data(calendar_data, server_date):
    """保存活动日历数据到JSON文件，用于后续调度"""
    data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "server_date": server_date,
        "activities": calendar_data
    }
    try:
        with open(CALENDAR_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Calendar data saved to {CALENDAR_DATA_FILE}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save calendar data: {e}")
        return False


def load_calendar_data():
    """加载已保存的活动日历数据"""
    try:
        with open(CALENDAR_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("[WARN] Calendar data file not found")
        return None
    except Exception as e:
        print(f"[ERROR] Failed to load calendar data: {e}")
        return None


def get_today_activities(calendar_data):
    """获取今天的活动"""
    today = datetime.now().strftime("%Y-%m-%d")
    for day_data in calendar_data:
        if day_data.get("date") == today:
            return day_data
    return None


def get_activity_dates(calendar_data):
    """获取所有活动日期列表"""
    return [day_data.get("date") for day_data in calendar_data if day_data.get("date")]


def generate_cron_schedule(calendar_data):
    """根据活动日历生成 cron 调度时间（北京时间凌晨0点执行）
    GitHub Actions 使用 UTC 时间，北京时间是 UTC+8
    所以北京时间 00:05 = UTC 前一天 16:05
    """
    schedules = []
    for day_data in calendar_data:
        date_str = day_data.get("date")
        if not date_str:
            continue
        try:
            activity_date = datetime.strptime(date_str, "%Y-%m-%d")
            # 北京时间当天00:05执行，即UTC时间前一天16:05
            utc_date = activity_date - timedelta(hours=8)
            # cron格式: 分 时 日 月 *
            cron = f"5 16 {utc_date.day} {utc_date.month} *"
            schedules.append({
                "date": date_str,
                "cron": cron,
                "activities_count": day_data.get("count", 0)
            })
        except ValueError:
            continue
    return schedules


def mode_fetch_calendar():
    """模式1: 仅获取活动日历（每月1日执行）"""
    print("=" * 60)
    print("Mode: Fetch Calendar (Monthly)")
    print("=" * 60)
    
    session_id, init_ok = initialize_session()
    if not init_ok:
        print("[ERROR] Session initialization failed!")
        return 1
    
    # 获取服务器时间
    time_resp = get_now_time(session_id)
    server_date = None
    if not time_resp.get("error"):
        structured = time_resp.get("result", {}).get("structuredContent", {})
        server_date = structured.get("data", {}).get("date")
    
    # 获取活动日历
    calendar_resp = get_calendar(session_id)
    if calendar_resp.get("error"):
        print(f"[ERROR] Calendar query failed: {calendar_resp['error']['message']}")
        return 1
    
    content = calendar_resp.get("result", {}).get("content", [])
    text = content[0].get("text", "") if content else ""
    calendar_data = parse_calendar_activities(text, server_date)
    
    if not calendar_data:
        print("[WARN] No activities found this month")
        return 0
    
    # 保存日历数据
    save_calendar_data(calendar_data, server_date)
    
    # 生成调度信息
    schedules = generate_cron_schedule(calendar_data)
    
    # 发送Telegram通知
    total = sum(a['count'] for a in calendar_data)
    dates = [s['date'] for s in schedules]
    
    msg = f"📅 *本月活动日历已更新*\n\n"
    msg += f"• 活动天数: {len(calendar_data)} 天\n"
    msg += f"• 总活动数: {total} 个\n\n"
    msg += f"*活动日期:*\n"
    for day_data in calendar_data[:10]:
        date = day_data['date']
        count = day_data['count']
        msg += f"• {date} ({count}个活动)\n"
    if len(calendar_data) > 10:
        msg += f"• ...还有{len(calendar_data)-10}天\n"
    
    if GITHUB_PAGES_URL:
        msg += f"\n🔗 [查看详情]({GITHUB_PAGES_URL})"
    
    send_telegram_message(msg)
    
    # 输出调度信息供 GitHub Actions 使用
    print("\n[Schedule Info]")
    for s in schedules:
        print(f"  {s['date']}: {s['cron']} ({s['activities_count']} activities)")
    
    # 输出为 GitHub Actions 输出格式
    dates_json = json.dumps(dates)
    print(f"\n::set-output name=activity_dates::{dates_json}")
    
    return 0


def mode_auto_claim():
    """模式2: 自动领取优惠券（每天或活动日执行）"""
    print("=" * 60)
    print("Mode: Auto Claim Coupons")
    print("=" * 60)
    
    session_id, init_ok = initialize_session()
    if not init_ok:
        print("[ERROR] Session initialization failed!")
        return 1
    
    # 获取服务器时间
    time_resp = get_now_time(session_id)
    server_date = None
    if not time_resp.get("error"):
        structured = time_resp.get("result", {}).get("structuredContent", {})
        server_date = structured.get("data", {}).get("date")
        print(f"[OK] Server date: {server_date}")
    
    # 检查今天是否有活动
    saved_data = load_calendar_data()
    today_activity = None
    if saved_data:
        today_activity = get_today_activities(saved_data.get("activities", []))
        if today_activity:
            print(f"[INFO] Today has {today_activity['count']} activities!")
    
    # 自动领券
    print("\n[1/3] Auto claiming coupons...")
    claim_resp = auto_claim_coupons(session_id)
    if claim_resp.get("error"):
        print(f"[ERROR] Claim failed: {claim_resp['error']['message']}")
        claim_result = {"success": 0, "failed": 0, "coupons": [], "message": ""}
    else:
        content = claim_resp.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        claim_result = parse_claim_result(text)
        if claim_result.get("message"):
            print(f"[INFO] {claim_result['message']}")
        else:
            print(f"[OK] Success: {claim_result['success']}, Failed: {claim_result['failed']}")
    
    # 查询我的优惠券
    print("\n[2/3] Querying my coupons...")
    my_coupons_resp = get_my_coupons(session_id)
    if my_coupons_resp.get("error"):
        print(f"[ERROR] Query failed: {my_coupons_resp['error']['message']}")
        my_coupons = []
    else:
        content = my_coupons_resp.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        my_coupons = parse_my_coupons(text)
        print(f"[OK] Found {len(my_coupons)} available coupons")
    
    # 获取日历数据用于报告
    calendar_data = saved_data.get("activities", []) if saved_data else []
    
    # 推送到Telegram
    print("\n[3/3] Pushing report...")
    report = format_report(calendar_data, claim_result, my_coupons, GITHUB_PAGES_URL)
    
    if send_telegram_message(report):
        print("[OK] Telegram message sent!")
    else:
        print("[WARN] Telegram message skipped or failed")
    
    # 生成并保存HTML报告
    html_content = generate_html_report(calendar_data, claim_result, my_coupons)
    html_path = "index.html"  # GitHub Pages 默认使用 index.html
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[OK] HTML report generated: {html_path}")
    except Exception as e:
        print(f"[ERROR] HTML generation failed: {e}")
    
    print("\n" + "=" * 60)
    print("Task completed!")
    print("=" * 60)
    
    return 0


def mode_full():
    """模式3: 完整流程（获取日历+领券+推送）"""
    print("=" * 60)
    print("Mode: Full Process")
    print("=" * 60)
    
    session_id, init_ok = initialize_session()
    if not init_ok:
        print("[ERROR] Session initialization failed!")
        return 1
    print("[OK] Session initialized")
    
    # 获取MCP服务器时间
    print("\n[1/5] Getting MCP server time...")
    time_resp = get_now_time(session_id)
    server_date = None
    if time_resp.get("error"):
        print("[WARN] Failed to get server time, using local time")
    else:
        structured = time_resp.get("result", {}).get("structuredContent", {})
        server_date = structured.get("data", {}).get("date")
        if server_date:
            print(f"[OK] Server date: {server_date}")
    
    # 查询活动日历
    print("\n[2/5] Querying activity calendar...")
    calendar_resp = get_calendar(session_id)
    if calendar_resp.get("error"):
        print(f"[ERROR] Calendar query failed: {calendar_resp['error']['message']}")
        calendar_data = []
    else:
        content = calendar_resp.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        calendar_data = parse_calendar_activities(text, server_date)
        total = sum(a['count'] for a in calendar_data)
        print(f"[OK] Found {len(calendar_data)} upcoming days with {total} activities")
        # 保存日历数据
        save_calendar_data(calendar_data, server_date)
    
    # 自动领券
    print("\n[3/5] Auto claiming coupons...")
    claim_resp = auto_claim_coupons(session_id)
    if claim_resp.get("error"):
        print(f"[ERROR] Claim failed: {claim_resp['error']['message']}")
        claim_result = {"success": 0, "failed": 0, "coupons": [], "message": ""}
    else:
        content = claim_resp.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        claim_result = parse_claim_result(text)
        if claim_result.get("message"):
            print(f"[INFO] {claim_result['message']}")
        else:
            print(f"[OK] Success: {claim_result['success']}, Failed: {claim_result['failed']}")
    
    # 查询我的优惠券
    print("\n[4/5] Querying my coupons...")
    my_coupons_resp = get_my_coupons(session_id)
    if my_coupons_resp.get("error"):
        print(f"[ERROR] Query failed: {my_coupons_resp['error']['message']}")
        my_coupons = []
    else:
        content = my_coupons_resp.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        my_coupons = parse_my_coupons(text)
        print(f"[OK] Found {len(my_coupons)} available coupons")
        if my_coupons:
            with_img = sum(1 for c in my_coupons if c.get('img'))
            print(f"[INFO] {with_img} coupons have images")
    
    # 推送到Telegram
    print("\n[5/5] Pushing report...")
    report = format_report(calendar_data, claim_result, my_coupons, GITHUB_PAGES_URL)
    
    if send_telegram_message(report):
        print("[OK] Telegram message sent!")
    else:
        print("[WARN] Telegram message skipped or failed")
    
    # 生成并保存HTML报告
    html_content = generate_html_report(calendar_data, claim_result, my_coupons)
    html_path = "index.html"
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[OK] HTML report generated: {html_path}")
    except Exception as e:
        print(f"[ERROR] HTML generation failed: {e}")
    
    print("\n" + "=" * 60)
    print("Task completed!")
    print("=" * 60)
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="McDonald's MCP Auto Claim Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行模式:
  calendar  - 仅获取活动日历（每月1日执行）
  claim     - 自动领取优惠券（每天或活动日执行）
  full      - 完整流程（获取日历+领券+推送）

示例:
  python auto_claim.py --mode calendar   # 每月1日获取日历
  python auto_claim.py --mode claim      # 自动领券
  python auto_claim.py --mode full       # 完整流程
  python auto_claim.py                   # 默认完整流程
        """
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["calendar", "claim", "full"],
        default="full",
        help="运行模式 (默认: full)"
    )
    
    args = parser.parse_args()
    
    if args.mode == "calendar":
        return mode_fetch_calendar()
    elif args.mode == "claim":
        return mode_auto_claim()
    else:
        return mode_full()


if __name__ == "__main__":
    sys.exit(main())
