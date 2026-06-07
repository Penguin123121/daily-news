"""
每日新闻摘要工具
从央视新闻获取近3天（今天/昨天/前天）关注度最高的前5条新闻，生成带日期切换功能的HTML报告。
保留最近3天数据，自动清理过期文件。
"""
import requests
import json
import re
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# 修复Windows终端中文编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
RETENTION_DAYS = 3
TOP_N = 5
MAX_PAGES = 8
BASE_URL = "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/news_{page}.jsonp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%d %H:%M"
FULL_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

PERIOD_MORNING = "morning"
PERIOD_EVENING = "evening"
PERIOD_LABELS = {PERIOD_MORNING: "早间", PERIOD_EVENING: "晚间"}


def get_weekday(date_str):
    return WEEKDAYS[datetime.strptime(date_str, DATE_FMT).weekday()]


def get_data_filepath(date_str):
    return os.path.join(OUTPUT_DIR, f"news_{date_str}.json")


def load_json_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def iter_data_files():
    try:
        for fname in os.listdir(OUTPUT_DIR):
            m = re.match(r'news_(\d{4}-\d{2}-\d{2})\.json$', fname)
            if m:
                yield m.group(1), os.path.join(OUTPUT_DIR, fname)
    except FileNotFoundError:
        return


def get_cutoff_date_str(days, now=None):
    ref = get_reference_date(now)
    return (ref - timedelta(days=days - 1)).strftime(DATE_FMT)


def is_in_time_window(focus_date_str, start, end):
    if not focus_date_str:
        return False
    try:
        focus_dt = datetime.strptime(focus_date_str, FULL_DATETIME_FMT)
        return start <= focus_dt <= end
    except ValueError:
        return True  # 解析失败时容错放行，避免因格式问题丢失新闻


def get_period(now=None):
    """根据当前小时判断时段：0-7无时段（新闻日未切换），8-19为早间，20-23为晚间"""
    if now is None:
        now = datetime.now()
    h = now.hour
    if h < 8:
        return None
    elif h < 20:
        return PERIOD_MORNING
    else:
        return PERIOD_EVENING


def get_time_window(period, reference_date=None):
    """返回指定时段的 focus_date 过滤范围 (start, end)。
    reference_date: 基准日期（默认今天）
    morning: 基准日前一天20:00 → 基准日08:00
    evening: 基准日08:00 → 基准日20:00
    """
    if reference_date is None:
        reference_date = datetime.now()
    today = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    if period == PERIOD_MORNING:
        return yesterday.replace(hour=20, minute=0, second=0), today.replace(hour=8, minute=0, second=0)
    else:
        return today.replace(hour=8, minute=0, second=0), today.replace(hour=20, minute=0, second=0)


def get_reference_date(now=None):
    """返回新闻意义上的'今天'：8点前为昨天，8点后为当天"""
    if now is None:
        now = datetime.now()
    if now.hour < 8:
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _get_morning_urls(existing_data):
    urls = set()
    if existing_data and PERIOD_MORNING in existing_data:
        for n in existing_data[PERIOD_MORNING].get("news", []):
            if n.get("url"):
                urls.add(n["url"])
    return urls


def fetch_news_page(page=1):
    url = BASE_URL.format(page=page)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] 请求第{page}页新闻列表失败: {e}")
        return []

    text = resp.content.decode("utf-8")

    # JSONP 格式: news({...})
    jsonp_match = re.search(r'news\((.*)\)', text, re.DOTALL)
    if not jsonp_match:
        print(f"[ERROR] 第{page}页未能解析JSONP响应")
        return []

    try:
        data = json.loads(jsonp_match.group(1))
    except json.JSONDecodeError as e:
        print(f"[ERROR] 第{page}页JSON解析失败: {e}")
        return []

    items = data.get("data", {}).get("list", [])
    return items


def fetch_all_recent_news(target_days=3, max_pages=MAX_PAGES, now=None):
    # 每个日期内按关注度排序：count降序 > 页面升序 > 页内位置升序
    if now is None:
        now = datetime.now()
    all_items = defaultdict(list)
    seen_urls = set()

    for page in range(1, max_pages + 1):
        items = fetch_news_page(page)
        if not items:
            print(f"[INFO] 第{page}页无数据，停止翻页")
            break

        page_added = 0
        for pos, item in enumerate(items):
            focus_date = item.get("focus_date", "").strip()
            if not focus_date:
                continue

            url = item.get("url", "").strip()
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

            date_str = focus_date[:10]
            count_val = item.get("count", "").strip()
            count_int = int(count_val) if count_val else 0
            all_items[date_str].append((item, page, pos, count_int))
            page_added += 1

        dedup_skipped = len(items) - page_added
        print(f"[INFO] 第{page}页获取 {len(items)} 条，去重后新增 {page_added} 条"
              + (f"，跳过 {dedup_skipped} 条重复" if dedup_skipped > 0 else ""))

    sorted_dates = sorted(all_items.keys(), reverse=True)
    result = {}
    cutoff_date = get_cutoff_date_str(target_days, now)

    for date_str in sorted_dates:
        if date_str >= cutoff_date:
            items_with_meta = all_items[date_str]
            # count降序 → 页面升序 → 位置升序，保证高关注度优先
            items_with_meta.sort(key=lambda x: (-x[3], x[1], x[2]))
            result[date_str] = [x[0] for x in items_with_meta]
            print(f"[INFO] {date_str}: 共 {len(result[date_str])} 条新闻")

    return result


def build_news_item(item):
    title = item.get("title", "").strip()
    url = item.get("url", "").strip()
    focus_date = item.get("focus_date", "").strip()
    brief = item.get("brief", "").strip()
    image = item.get("image", "").strip()

    if not title or not url:
        return None

    summary = brief if brief else title
    if len(summary) > 200:
        summary = summary[:197] + "..."

    return {
        "title": title,
        "url": url,
        "time": focus_date,
        "summary": summary,
        "image": image,
    }


def save_day_data(date_str, news_list, period=None, now=None):
    """保存单日新闻数据为JSON文件。
    period='morning': 写入morning字段，保留已有evening
    period='evening': 写入evening字段，保留已有morning
    """
    filepath = get_data_filepath(date_str)
    if now is None:
        now = datetime.now()
    now_str = now.strftime(DATETIME_FMT)
    weekday = get_weekday(date_str)

    if period is None:
        data = {
            "date": date_str,
            "weekday": weekday,
            "news": news_list,
            "generated": now_str,
        }
    else:
        existing = load_json_file(filepath) or {}

        data = {
            "date": date_str,
            "weekday": weekday,
        }
        if PERIOD_MORNING in existing:
            data[PERIOD_MORNING] = existing[PERIOD_MORNING]
        if PERIOD_EVENING in existing:
            data[PERIOD_EVENING] = existing[PERIOD_EVENING]
        data[period] = {
            "news": news_list,
            "generated": now_str,
        }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath


def load_all_days():
    """加载所有可用日期的新闻数据，按日期降序排列。
    兼容旧格式({news, generated})和新格式({morning, evening})。
    """
    days = []
    for date_str, fpath in iter_data_files():
        day = load_json_file(fpath)
        if day is None:
            print(f"[WARN] 读取 news_{date_str}.json 失败")
            continue
        if "news" in day and PERIOD_MORNING not in day and PERIOD_EVENING not in day:
            day = {
                "date": day["date"],
                "weekday": day.get("weekday", ""),
                "legacy": {
                    "news": day["news"],
                    "generated": day.get("generated", ""),
                }
            }
        days.append(day)
    days.sort(key=lambda d: d["date"], reverse=True)
    return days


def generate_html(all_days, now=None):
    """生成带日期切换和早晚双板块的HTML报告（传统中式邸报风格）"""
    if now is None:
        now = datetime.now()
    ref_date = get_reference_date(now)

    # 中文日期格式：二〇二六年六月六日
    CN_DIGITS = "〇一二三四五六七八九"
    CN_NUMS_10 = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

    def to_cn_year(y):
        return "".join(CN_DIGITS[int(c)] for c in str(y))

    def to_cn_md(n):
        if n <= 10:
            return CN_NUMS_10[n]
        if n < 20:
            return "十" + CN_NUMS_10[n % 10]
        tens = CN_NUMS_10[n // 10]
        ones = CN_NUMS_10[n % 10] if n % 10 != 0 else ""
        return tens + "十" + ones
    year_cn = to_cn_year(ref_date.year)
    month_cn = to_cn_md(ref_date.month)
    day_cn = to_cn_md(ref_date.day)
    cn_date = f"{year_cn}年{month_cn}月{day_cn}日"
    cn_weekday = WEEKDAYS[ref_date.weekday()]
    cn_header_date = f"{cn_date} · {cn_weekday}"

    # 用于页面底部显示的生成时间
    now_str = now.strftime(DATETIME_FMT)

    days_json = json.dumps(all_days, ensure_ascii=False)

    # 新闻数据中的日期用于 tab 显示
    def format_tab_date(date_str):
        dt = datetime.strptime(date_str, DATE_FMT)
        return f"{to_cn_md(dt.month)}月{to_cn_md(dt.day)}日"

    # 预计算 tab 日期中文格式，注入到 JS
    tab_dates_json = json.dumps({d["date"]: format_tab_date(d["date"]) for d in all_days}, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日新闻摘要</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
        background: #faf6ef;
        color: #333;
        line-height: 1.6;
    }}
    /* 宣纸纹理背景 */
    body::before {{
        content: '';
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background:
            radial-gradient(ellipse at 20% 50%, rgba(200,160,120,0.06) 0%, transparent 50%),
            radial-gradient(ellipse at 80% 20%, rgba(180,140,100,0.04) 0%, transparent 50%);
        pointer-events: none;
        z-index: 0;
    }}
    .container {{ width: 95%; max-width: none; margin: 0 auto; padding: 20px 20px 40px; position: relative; z-index: 1; }}

    /* ===== 匾额式 Header ===== */
    .header {{
        text-align: center;
        padding: 32px 20px 24px;
        background: linear-gradient(175deg, #6b1000 0%, #8b0000 40%, #a01010 100%);
        color: #f5e6c8;
        border-radius: 10px;
        margin-bottom: 24px;
        box-shadow: 0 4px 24px rgba(107, 16, 0, 0.35);
        position: relative;
        border: 1px solid rgba(180, 130, 80, 0.3);
    }}
    .header::before {{
        content: '';
        position: absolute;
        top: 6px; left: 10px; right: 10px;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(245,230,200,0.5), transparent);
    }}
    .header::after {{
        content: '';
        position: absolute;
        bottom: 6px; left: 10px; right: 10px;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(245,230,200,0.3), transparent);
    }}
    .header .brand-line {{
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
        font-size: 10px;
        letter-spacing: 4px;
        opacity: 0.45;
        text-transform: uppercase;
        margin-bottom: 6px;
    }}
    .header h1 {{
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
        font-size: 28px;
        font-weight: 700;
        letter-spacing: 8px;
        margin-bottom: 6px;
    }}
    .header .divider {{
        width: 48px;
        height: 1px;
        background: #d4a574;
        margin: 10px auto;
        opacity: 0.6;
    }}
    .header .date-line {{
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
        font-size: 11px;
        opacity: 0.5;
        letter-spacing: 2px;
    }}
    .header .gen-time {{
        font-size: 10px;
        opacity: 0.35;
        margin-top: 8px;
    }}

    /* ===== 日期 Tab 栏 ===== */
    .tabs {{
        display: flex;
        gap: 6px;
        margin-bottom: 24px;
    }}
    .tab {{
        flex: 1;
        text-align: center;
        padding: 12px 6px 10px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        color: #b8a088;
        background: #fdf8f3;
        border: 1px solid #e8d5c4;
        border-radius: 8px;
        outline: none;
        transition: all 0.25s;
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
    }}
    .tab:hover {{
        color: #8b4513;
        background: #fef5ec;
        border-color: #c0392b;
    }}
    .tab.active {{
        color: #f5e6c8;
        background: linear-gradient(175deg, #8b0000, #a01010);
        border-color: #6b1000;
        font-weight: 700;
        box-shadow: 0 2px 12px rgba(139, 0, 0, 0.25);
    }}
    .tab .tab-weekday {{ font-size: 16px; }}
    .tab .tab-date {{ font-size: 10px; display: block; margin-top: 3px; opacity: 0.7; }}

    /* ===== 面板 ===== */
    .day-panel {{ display: none; }}
    .day-panel.active {{
        display: flex;
        gap: 20px;
        align-items: flex-start;
    }}
    /* 时段分区列 */
    .period-col {{
        flex: 1;
        min-width: 0;
    }}
    .period-divider {{
        width: 1px;
        background: linear-gradient(180deg, transparent, #d4b896 15%, #d4b896 85%, transparent);
        flex-shrink: 0;
        align-self: stretch;
    }}

    /* ===== 时段板块标题 ===== */
    .period-section {{ margin-bottom: 24px; }}
    .period-header {{
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 0 0 12px 0;
        margin-bottom: 16px;
        border-bottom: 1px solid #e8d5c4;
    }}
    .period-stamp {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 48px;
        height: 48px;
        border-radius: 4px;
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
        font-size: 18px;
        font-weight: 700;
        color: #f5e6c8;
        flex-shrink: 0;
        letter-spacing: 2px;
        writing-mode: vertical-rl;
    }}
    .period-stamp.morning {{ background: #c0392b; box-shadow: 0 2px 8px rgba(192,57,43,0.3); }}
    .period-stamp.evening {{ background: #2c3e50; box-shadow: 0 2px 8px rgba(44,62,80,0.3); }}
    .period-stamp.legacy {{ background: #8b0000; box-shadow: 0 2px 8px rgba(139,0,0,0.3); }}
    .period-info {{ flex: 1; }}
    .period-info .period-label {{
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
        font-size: 18px;
        font-weight: 700;
        color: #4a3020;
    }}
    .period-info .period-meta {{
        font-size: 11px;
        color: #b8a088;
        margin-top: 2px;
    }}

    /* ===== 新闻卡片 ===== */
    .news-item {{
        display: flex;
        gap: 14px;
        background: #fff;
        border: 1px solid #e8d5c4;
        border-radius: 8px;
        padding: 18px;
        margin-bottom: 12px;
        transition: transform 0.2s, box-shadow 0.2s;
    }}
    .news-item:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(139, 69, 19, 0.1);
        border-color: #c0392b;
    }}
    /* 序号印章 */
    .news-rank {{
        flex-shrink: 0;
        width: 34px;
        height: 34px;
        color: #f5e6c8;
        font-size: 16px;
        font-weight: 700;
        border-radius: 3px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
    }}
    .news-rank.morning {{ background: #c0392b; }}
    .news-rank.evening {{ background: #2c3e50; }}
    .news-rank.legacy {{ background: #8b0000; }}
    .news-body {{ flex: 1; min-width: 0; }}
    .news-title {{
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
        font-size: 17px;
        font-weight: 700;
        margin-bottom: 4px;
        line-height: 1.5;
    }}
    .news-title a {{ color: #2a1a10; text-decoration: none; }}
    .news-title a:hover {{ color: #c0392b; }}
    .news-meta {{
        font-size: 12px;
        color: #b8a088;
        margin-bottom: 8px;
    }}
    .news-img {{ margin-bottom: 10px; }}
    .news-img img {{
        width: 100%;
        max-height: 280px;
        object-fit: cover;
        border-radius: 4px;
        border: 1px solid #f0e6d3;
    }}
    .news-summary {{
        font-size: 14px;
        color: #666;
        margin-bottom: 8px;
        text-align: justify;
        line-height: 1.7;
    }}
    .news-link {{
        display: inline-block;
        font-size: 13px;
        color: #c0392b;
        text-decoration: none;
        font-weight: 500;
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
    }}
    .news-link:hover {{ text-decoration: underline; color: #8b0000; }}

    /* ===== 占位 ===== */
    .period-placeholder {{
        text-align: center;
        padding: 28px 20px;
        color: #c8b898;
        font-size: 14px;
        background: #fdf8f3;
        border: 1px dashed #e8d5c4;
        border-radius: 8px;
        margin-bottom: 12px;
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
    }}
    .no-data {{
        text-align: center;
        padding: 40px 20px;
        color: #c8b898;
        font-size: 14px;
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
    }}
    .empty {{
        text-align: center;
        padding: 50px 20px;
        color: #b8a088;
        font-size: 15px;
        font-family: Georgia, "Noto Serif SC", "Source Han Serif SC", serif;
    }}

    /* ===== Footer ===== */
    .footer {{
        text-align: center;
        padding: 24px 20px;
        color: #c8b898;
        font-size: 12px;
        margin-top: 16px;
        border-top: 1px solid #e8d5c4;
    }}
    .footer a {{ color: #8b4513; text-decoration: none; }}
    .footer a:hover {{ color: #c0392b; }}

    /* ===== 移动端 ===== */
    @media (max-width: 600px) {{
        .container {{ padding: 12px 10px 30px; }}
        .header {{ padding: 24px 14px 18px; }}
        .header h1 {{ font-size: 22px; letter-spacing: 4px; }}
        /* 两列回退上下排列 */
        .day-panel.active {{
            flex-direction: column;
            gap: 0;
        }}
        .period-divider {{
            display: none;
        }}
        .news-item {{ padding: 14px; gap: 10px; }}
        .news-title {{ font-size: 15px; }}
        .news-summary {{ font-size: 13px; }}
        .news-img img {{ max-height: 200px; }}
        .period-stamp {{ width: 38px; height: 38px; font-size: 15px; }}
    }}
</style>
</head>
<body>
<div class="container">
    <!-- 匾额式 Header -->
    <div class="header">
        <div class="brand-line">— 央视新闻 —</div>
        <h1>每日新闻</h1>
        <div class="divider"></div>
        <div class="date-line">{cn_header_date}</div>
        <div class="gen-time">生成于 {now_str}</div>
    </div>

    <div class="tabs" id="tabBar"></div>

    <div id="panelContainer"></div>

    <div class="footer">
        <p>数据来源：<a href="https://news.cctv.com/" target="_blank">央视新闻 (news.cctv.com)</a></p>
        <p>自动生成 · 保留最近{RETENTION_DAYS}天 · 每日朝暮更新</p>
    </div>
</div>

<script>
var daysData = {days_json};
var tabDates = {tab_dates_json};
var CN_NUMS = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"];
var PERIOD_CONFIG = {{
    morning: {{ label: "朝闻", stampColor: "#c0392b", rankColor: "#c0392b" }},
    evening: {{ label: "暮览", stampColor: "#2c3e50", rankColor: "#2c3e50" }},
    legacy: {{ label: "新闻", stampColor: "#8b0000", rankColor: "#8b0000" }}
}};

function buildTab(d, index, active) {{
    var cls = "tab" + (active ? " active" : "");
    var cnDate = tabDates[d.date] || d.date;
    return '<button class="' + cls + '" onclick="switchDay(' + index + ')">'
        + '<span class="tab-weekday">' + d.weekday + '</span>'
        + '<span class="tab-date">' + cnDate + '</span></button>';
}}

function buildNewsItem(n, i, period) {{
    var rankNum = CN_NUMS[i + 1] || (i + 1);
    var imgTag = n.image
        ? '<div class="news-img"><img src="' + n.image + '" alt="" loading="lazy" onerror="this.style.display=\\'none\\'"></div>'
        : '';
    return '<div class="news-item">'
        + '<div class="news-rank ' + period + '">' + rankNum + '</div>'
        + '<div class="news-body">'
        + '<h2 class="news-title"><a href="' + n.url + '" target="_blank">' + n.title + '</a></h2>'
        + '<div class="news-meta">' + n.time + '</div>'
        + imgTag
        + '<p class="news-summary">' + n.summary + '</p>'
        + '<a class="news-link" href="' + n.url + '" target="_blank">查看原文 →</a>'
        + '</div></div>';
}}

function buildPeriodSection(periodData, period) {{
    var cfg = PERIOD_CONFIG[period] || PERIOD_CONFIG.legacy;
    var html = '<div class="period-section">';
    if (periodData && periodData.news && periodData.news.length > 0) {{
        var genText = periodData.generated ? '更新于 ' + periodData.generated : '';
        html += '<div class="period-header">'
            + '<div class="period-stamp ' + period + '">' + cfg.label + '</div>'
            + '<div class="period-info">'
            + '<div class="period-label">' + cfg.label + '新闻（' + periodData.news.length + '条）</div>'
            + '<div class="period-meta">' + genText + '</div>'
            + '</div></div>';
        periodData.news.forEach(function(n, i) {{
            html += buildNewsItem(n, i, period);
        }});
    }} else {{
        html += '<div class="period-header">'
            + '<div class="period-stamp ' + period + '">' + cfg.label + '</div>'
            + '<div class="period-info">'
            + '<div class="period-label">' + cfg.label + '新闻</div>'
            + '<div class="period-meta">尚未更新</div>'
            + '</div></div>';
        html += '<div class="period-placeholder">' + cfg.label + '新闻尚未更新，请稍候...</div>';
    }}
    html += '</div>';
    return html;
}}

function buildPanel(d, active) {{
    var cls = "day-panel" + (active ? " active" : "");
    var html = '<div class="' + cls + '" id="panel' + d.date + '">';

    if (d.morning || d.evening) {{
        html += '<div class="period-col">' + buildPeriodSection(d.morning, "morning") + '</div>';
        html += '<div class="period-divider"></div>';
        html += '<div class="period-col">' + buildPeriodSection(d.evening, "evening") + '</div>';
    }} else if (d.legacy && d.legacy.news && d.legacy.news.length > 0) {{
        html += '<div class="period-col">' + buildPeriodSection(d.legacy, "legacy") + '</div>';
    }} else {{
        html += '<div class="no-data">该日暂无新闻数据</div>';
    }}
    html += '</div>';
    return html;
}}

function switchDay(index) {{
    var tabs = document.querySelectorAll(".tab");
    var panels = document.querySelectorAll(".day-panel");
    tabs.forEach(function(t, i) {{ t.className = (i === index) ? "tab active" : "tab"; }});
    panels.forEach(function(p, i) {{ p.className = (i === index) ? "day-panel active" : "day-panel"; }});
}}

function render() {{
    var tabBar = document.getElementById("tabBar");
    var panelContainer = document.getElementById("panelContainer");
    if (daysData.length === 0) {{
        tabBar.innerHTML = "";
        panelContainer.innerHTML = '<div class="empty">暂无新闻数据，请运行脚本获取</div>';
        return;
    }}
    var tabHtml = "";
    var panelHtml = "";
    daysData.forEach(function(d, i) {{
        tabHtml += buildTab(d, i, i === 0);
        panelHtml += buildPanel(d, i === 0);
    }});
    tabBar.innerHTML = tabHtml;
    panelContainer.innerHTML = panelHtml;
}}

render();
</script>
</body>
</html>"""
    return html


def cleanup_old_files(now=None):
    """删除超过保留天数的旧JSON数据文件"""
    cutoff = get_cutoff_date_str(RETENTION_DAYS, now)
    for date_str, fpath in iter_data_files():
        if date_str < cutoff:
            try:
                os.remove(fpath)
                print(f"[CLEAN] 已删除过期数据: news_{date_str}.json")
            except OSError as e:
                print(f"[WARN] 删除 news_{date_str}.json 失败: {e}")


def _collect_period_news(items, period, morning_urls, reference_date):
    time_start, time_end = get_time_window(period, reference_date)
    print(f"[INFO] 时间窗口: {time_start.strftime('%m-%d %H:%M')} → {time_end.strftime('%m-%d %H:%M')}")

    news_list = []
    for item in items:
        focus_date = item.get("focus_date", "").strip()
        if not is_in_time_window(focus_date, time_start, time_end):
            continue

        news_item = build_news_item(item)
        if not news_item:
            continue
        if period == PERIOD_EVENING and news_item["url"] in morning_urls:
            continue
        news_list.append(news_item)
        if len(news_list) >= TOP_N:
            break
    return news_list


def _process_period(period, all_days_raw, ref_date_str, now):
    """为一个时段生成新闻数据，返回保存的日期数量"""
    period_label = PERIOD_LABELS[period]

    if ref_date_str not in all_days_raw:
        print(f"[INFO] 新闻日({ref_date_str})暂无新闻数据（可能尚未更新）")

    # 晚间：加载新闻日已有数据用于去重
    today_existing = None
    morning_urls = set()
    if period == PERIOD_EVENING:
        today_existing = load_json_file(get_data_filepath(ref_date_str))
        morning_urls = _get_morning_urls(today_existing)
        if morning_urls:
            print(f"[INFO] 早间已有 {len(morning_urls)} 条新闻，晚间将排除重复")

    saved_count = 0
    for date_str in sorted(all_days_raw.keys(), reverse=True):
        items = all_days_raw[date_str]
        reference_date = datetime.strptime(date_str, DATE_FMT)
        is_today = (date_str == ref_date_str)

        # 非今日：已有当前时段数据则跳过
        existing = None
        if not is_today:
            existing = load_json_file(get_data_filepath(date_str))
            if existing and ("news" in existing or period in existing):
                print(f"[SKIP] {date_str}: {period_label}数据已存在，跳过")
                saved_count += 1
                continue

        # 晚间去重：从已有数据提取早间URL
        urls_to_exclude = set()
        if period == PERIOD_EVENING:
            source = today_existing if is_today else existing
            urls_to_exclude = _get_morning_urls(source)
            if urls_to_exclude and not is_today:
                print(f"[INFO] {date_str} 早间已有 {len(urls_to_exclude)} 条，晚间将排除重复")

        # 早间跨日期新闻池：纳入前一天20:00后发布的条目
        pool_items = list(items)
        if period == PERIOD_MORNING:
            prev_date_str = (reference_date - timedelta(days=1)).strftime(DATE_FMT)
            if prev_date_str in all_days_raw:
                pool_items.extend(all_days_raw[prev_date_str])

        news_list = _collect_period_news(pool_items, period, urls_to_exclude, reference_date)
        label_suffix = " " if is_today else "(补) "

        if news_list:
            canonical_hour = 8 if period == PERIOD_MORNING else 20
            canonical_now = reference_date.replace(hour=canonical_hour, minute=0, second=0, microsecond=0)
            json_path = save_day_data(date_str, news_list, period=period, now=canonical_now)
            weekday = get_weekday(date_str)
            print(f"[SAVED] {date_str} ({weekday}): {period_label}{label_suffix}{len(news_list)}条 -> {os.path.basename(json_path)}")
            saved_count += 1
        elif is_today:
            print(f"[WARN] {date_str}: 时间窗口内无新闻（可能该时段新闻尚未发布）")
        else:
            print(f"[WARN] {date_str}: 无有效新闻条目")

    return saved_count


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    now = datetime.now()
    period = get_period(now)
    ref_date = get_reference_date(now)
    ref_date_str = ref_date.strftime(DATE_FMT)

    # 0:00-7:59：新闻日尚未切换，不抓取新数据，仅基于已有数据重建HTML
    if period is None:
        print(f"[INFO] ========== 新闻日尚未切换 ==========")
        print(f"[INFO] 当前时间: {now.strftime(DATETIME_FMT)}，新闻日: {ref_date_str}")
        print(f"[INFO] 早间新闻将在 8:00 更新，当前仅展示已有数据")
        cleanup_old_files(now)
        all_days = load_all_days()
        if all_days:
            print(f"[INFO] 当前共 {len(all_days)} 天数据: {[d['date'] + ' ' + d['weekday'] for d in all_days]}")
            html = generate_html(all_days, now)
            html_path = os.path.join(OUTPUT_DIR, "index.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[INFO] 报告已生成: {html_path}")
        else:
            print("[ERROR] 没有任何新闻数据，请等待 8:00 首次更新")
        print("[INFO] ========== 完成 ==========")
        return

    print(f"[INFO] ========== 开始获取新闻 ==========")
    print(f"[INFO] 当前时间: {now.strftime(DATETIME_FMT)}，新闻日: {ref_date_str}")
    print(f"[INFO] 目标: 获取最近{RETENTION_DAYS}天的新闻")

    all_days_raw = fetch_all_recent_news(target_days=RETENTION_DAYS, max_pages=MAX_PAGES, now=now)

    if not all_days_raw:
        print("[ERROR] 未能获取任何新闻，退出")
        return

    print(f"[INFO] 共覆盖 {len(all_days_raw)} 个日期: {sorted(all_days_raw.keys(), reverse=True)}")

    # 自动补全当天缺失的时段
    periods_to_run = []
    today_data = load_json_file(get_data_filepath(ref_date_str))
    if now.hour >= 8 and (not today_data or PERIOD_MORNING not in today_data):
        periods_to_run.append(PERIOD_MORNING)
    if now.hour >= 20 and (not today_data or PERIOD_EVENING not in today_data):
        periods_to_run.append(PERIOD_EVENING)
    # 即使今天数据完整，也运行当前时段以补全其他日期的缺失数据
    if period not in periods_to_run:
        periods_to_run.append(period)

    if len(periods_to_run) > 1:
        labels = [PERIOD_LABELS[p] for p in periods_to_run]
        print(f"[INFO] 检测到缺失时段，将依次生成: {', '.join(labels)}")

    for i, p in enumerate(periods_to_run):
        if i > 0:
            print()  # 时段之间空一行
        _process_period(p, all_days_raw, ref_date_str, now)

    # 只跑了早间时，清除今日可能残留的晚间数据
    if periods_to_run == [PERIOD_MORNING]:
        today_data = load_json_file(get_data_filepath(ref_date_str))
        if today_data and PERIOD_EVENING in today_data:
            del today_data[PERIOD_EVENING]
            with open(get_data_filepath(ref_date_str), "w", encoding="utf-8") as f:
                json.dump(today_data, f, ensure_ascii=False, indent=2)
            print(f"[INFO] 已清除 {ref_date_str} 的残留晚间数据（晚间将在 20:00 更新）")

    cleanup_old_files(now)

    all_days = load_all_days()
    print(f"[INFO] 当前共 {len(all_days)} 天数据: {[d['date'] + ' ' + d['weekday'] for d in all_days]}")

    html = generate_html(all_days, now)
    html_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[INFO] 报告已生成: {html_path}")

    print("[INFO] ========== 完成 ==========")


if __name__ == "__main__":
    main()
