# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

每日新闻摘要工具 — 从央视新闻 API 抓取近3天关注度最高的新闻，每日分早晚两次更新（8:00 / 20:00），生成带日期切换标签和早晚双板块的 HTML 报告。每个板块各含 5 条不重复的热度新闻。

## 新闻内容多样性原则

- 尽量保持新闻内容的多样性，避免同一事件的不同报道占据多个位置。
- 如果多条新闻主题相似（如均为同一事件的不同侧面），优先保留关注度最高的那条，其余留给其他主题。
- 晚间新闻自动排除早间已有的新闻，保证早晚板块无重复。

## 新闻更新规则

- 新闻更新时，从上次更新到本次更新的时间段内的所有新闻中进行筛选。
- **早间更新（8:00）**：筛选前一天 20:00 至当日 8:00 之间发布的热度最高 5 条。
- **晚间更新（20:00）**：筛选当日 8:00 至 20:00 之间发布的热度最高 5 条，排除早间已选新闻。
- 非今日日期的已有数据不会被覆盖，保证历史早晚板块完整保留。
- **自动补全机制**：无论何时运行脚本，都会检测当天是否缺失早间/晚间数据并自动补全。例如晚上 9 点打开电脑（错过早间定时任务），脚本会自动先补早间再跑晚间，确保用户总能看到最完整的新闻内容。

## 运行方式

```bash
# 手动运行一次（自动判断时段：8:00-19:59为早间，20:00-23:59为晚间，0:00-7:59不更新）
python fetch_news.py

# 通过批处理手动运行（设置 UTF-8 编码 + 指定路径）
run_daily.bat

# 一键更新 + 打开报告（桌面快捷方式指向此文件）
open_news.bat
```

Python 路径硬编码在 `run_daily.bat` 中（Python 3.7），如需更换版本请修改该文件。

### Windows 定时任务

每天 8:00 + 20:00 自动运行，无需打开任何程序。定时任务有 **2 个**（因 schtasks.exe 不支持单任务多触发器）：

| 任务名 | 运行时间 |
|--------|---------|
| `daily-news-morning` | 每天 08:00 |
| `daily-news-evening` | 每天 20:00 |

**创建/修复定时任务：** 以管理员身份打开 CMD，运行：

```cmd
C:\Users\13422\AppData\Local\Programs\Python\Python37\python.exe "C:\Claude Code\Claude 终端项目\daily-news\fix_task.py"
```

**桌面快捷方式：** `每日新闻.lnk` → 指向 `open_news.vbs`，使用 `每日新闻软件图标.ico` 作为图标。

> **一键更新设计：** 用户要求打开电脑后，只需点击桌面快捷方式就能看到最新新闻，无需手动运行脚本或进入 Claude Code。
> 
> **为什么用 VBS 而非 BAT：** BAT 文件含中文路径时必须保存为 GBK 编码，且 CMD 的 `chcp 65001` 在文件读取阶段不生效，导致中文路径乱码。VBScript（UTF-16 LE）是 Windows 原生支持的 Unicode 格式，中文路径不会出现编码问题。
> 
> **执行流程：** `open_news.vbs` → 静默运行 `fetch_news.py`（后台执行，无窗口）→ 等待完成后自动打开浏览器显示 `output/index.html`。

## 架构

单文件应用 `fetch_news.py`，无外部依赖（仅标准库 + `requests`）。

**数据流:**
1. `get_period()` — 根据当前小时判断时段（8-19=morning, 20-23=evening, 0-7=None，新闻日以8:00为界）
2. `get_reference_date()` — 返回新闻意义上的"今天"（8点前为昨天，8点后为当天）
3. `get_time_window(period)` — 返回时段对应的 focus_date 过滤范围
4. `fetch_news_page(page)` — 从央视 JSONP API 获取单页新闻列表
5. `fetch_all_recent_news()` — 遍历多页，按 `focus_date` 字段聚合新闻，按关注度排序 + URL去重
6. `build_news_item()` — 将原始条目标准化（title/url/time/summary/image）
7. `save_day_data(date_str, news_list, period)` — 按日期+时段保存为 `output/news_YYYY-MM-DD.json`，支持合并写入（晚间保留早间数据）
8. `load_all_days()` — 加载所有可用日期的 JSON 数据，兼容新旧两种格式
9. `generate_html()` — 将全部日期数据内嵌生成静态 HTML，早晚两个子板块独立展示
10. `cleanup_old_files()` — 按文件名日期删除超出保留天数的 JSON 文件

**关键配置常量（`fetch_news.py` 顶部）:**
- `OUTPUT_DIR` = `./output`（与脚本同目录）
- `RETENTION_DAYS` = 3
- `TOP_N` = 5（每个时段保留多少条，全天共 10 条）
- `MAX_PAGES` = 8（API 翻页上限）

**JSON 数据格式（新格式）:**
```json
{
  "date": "2026-05-14", "weekday": "周四",
  "morning": {"news": [...], "generated": "2026-05-14 08:05"},
  "evening": {"news": [...], "generated": "2026-05-14 20:05"}
}
```

**输出结构:** `output/` 目录包含每日 JSON 文件 + `index.html`（单文件，所有数据内嵌，可直接用浏览器打开）。

## 踩过的坑 & 经验教训

### 1. Windows 中文路径 + 定时任务 = 编码雷区

**问题：** 项目路径 `C:\Claude Code\Claude 终端项目\daily-news\` 包含中文字符。用 PowerShell 脚本注册 Windows 定时任务时，中文路径被错误编码为乱码，导致任务找不到文件（上次运行结果 = 2，即 `ERROR_FILE_NOT_FOUND`）。

**根因：** PowerShell 脚本文件编码与运行时编码不一致，`Register-ScheduledTask` cmdlet 在注册时把路径中的"终端项目"写成了乱码。

**解决方案：** 用 Python + `subprocess` 调用 `schtasks.exe`，Python 的字符串编码处理比 PowerShell 可靠得多。见 `fix_task.py`。

**教训：**
- 在 Windows 上操作中文路径时，**优先用 Python 而非 PowerShell** 来调用系统命令
- `subprocess.run(..., encoding="gbk")` 是处理 Windows 中文输出的正确姿势
- `.bat` 文件含中文时，必须保存为 **GBK/ANSI 编码**，UTF-8 无 BOM 会被 CMD 误读为乱码
- `chcp 65001` 不一定能解决 CMD 的中文显示问题，取决于终端字体

### 2. schtasks.exe 不支持单任务多触发器

**问题：** 想创建一个任务在 8:00 和 20:00 各跑一次，但 `schtasks /Create` 每个任务只支持一个触发器。用同名创建两次，第二次会覆盖第一次。

**解决方案：** 创建两个独立任务 `daily-news-morning` 和 `daily-news-evening`。

**对比：**
| 方式 | 单任务双触发器 | 双任务单触发器 |
|------|:--:|:--:|
| schtasks.exe | ❌ 不支持 | ✅ 可行 |
| PowerShell Register-ScheduledTask | ✅ 可行 | — |
| GUI taskschd.msc | ✅ 可行 | — |

### 3. PowerShell 脚本闪退的常见原因

- **缺 `Read-Host` / `pause`：** 脚本执行完立刻关窗，看不到输出
- **执行策略拦截：** 系统 `ExecutionPolicy` 阻止脚本运行，窗口一闪而过
- **权限不足：** `Unregister-ScheduledTask` / `Register-ScheduledTask` 需要管理员权限，权限不够直接报错退出

**解决方案：** 用 `.bat` 做启动器（`pause` 保底），或 `fix_task.py` 用 `input()` 停住窗口。

### 4. 代码审查（/simplify）经验

对 `fetch_news.py`（约 700 行单文件应用）做了一次完整的三 Agent 并行审查（复用/质量/效率），主要改进：

- **提取 `_get_morning_urls()` 辅助函数** — 消除早晚去重逻辑的复制粘贴（两处约 8 行重复代码）
- **删除 `save_day_data` 的 `existing_data` 参数** — 消除抽象泄漏，让函数自己负责读取已有数据
- **主循环扁平化** — 用 early continue 替代 `is_today`/`else` 3 层嵌套，从 ~30 行缩到 ~20 行
- **删除约 15 处冗余注释** — 只保留解释"为什么"的注释（如容错逻辑、排序规则）
- **修复 TOCTOU 反模式** — `iter_data_files` 改用 try/except FileNotFoundError 替代 `os.path.exists` 预检查
- **精简异常捕获** — `load_json_file` 去掉冗余的 `OSError`（`FileNotFoundError` 已是其子类）
- **`create_task.py` 用循环消除重复** — 早晚两个 `subprocess.run` 合并为循环
- **清理 3 个冗余文件** — `create_task.ps1`（与 `setup_scheduler.ps1` 重复）、`create_task.py`（已被 `fix_task.py` 取代）、`__pycache__/`

代码行数从 ~700 缩减且逻辑更清晰，功能行为完全保持不变。

### 5. BAT 快捷方式 + 中文路径 = 闪退（即使设了 chcp 65001）

**问题：** 创建 `open_news.bat` 作为桌面快捷方式目标，双击后 CMD 窗口一闪而过，既不报错也不打开浏览器。

**排查过程：**
1. 怀疑 `start` 命令语法 → 改用 `explorer` 同样闪退 → 排除
2. 怀疑快捷方式「起始位置」设置 → 手工运行 bat 同样闪退 → 排除
3. 用 GBK 编码重写 bat → 问题依旧

**根因：** `chcp 65001` 只影响 CMD 运行时的**输出编码**，不影响 CMD **读取 bat 文件**时的解码方式。CMD 始终用系统默认编码（中文 Windows = GBK）读取 bat 文件。文件本身如果是 UTF-8，中文路径在 CMD 读到的那一刻就已经是乱码了，后续所有命令（`cd`、`start`、`explorer`）都找不到目标。

**为什么 `iconv -f UTF-8 -t GBK` 转换后仍然不行：** Git Bash 环境下的 `iconv` 转换不可靠，路径中的中文经它转换后可能出现字节级偏差。

**为什么 Python `encoding='gbk'` 写入后仍然不行：** 需要严格验证——如果中途用 Read 工具查看内容，Read 工具以 UTF-8 解码显示的乱码容易误导判断。

**最终方案：** 放弃 BAT，改用 **VBScript（`open_news.vbs`）**：
- VBS 文件保存为 **UTF-16 LE** 编码，这是 Windows 原生 Unicode 格式，中文路径零问题
- `WshShell.Run` 的 `window_style=0` 实现完全后台静默执行（无 CMD 窗口闪现）
- `wait=True` 确保 Python 跑完后再打开浏览器

**VBS 关键代码模板：**
```vbscript
Set WshShell = CreateObject("WScript.Shell")
' 后台静默执行 Python，等待完成
WshShell.Run "python.exe ""脚本路径.py""", 0, True
' 前台打开 HTML 报告
WshShell.Run """报告路径.html""", 1
```

**VBS 引号转义规则（避坑）：**
- VBS 字符串内部用 `""` 表示一个双引号
- 例：`"python.exe ""C:\路径\脚本.py"""`  →  实际传给 Shell 的是 `python.exe "C:\路径\脚本.py"`
- 例：`"""C:\路径\文件.html"""`  →  实际传给 Shell 的是 `"C:\路径\文件.html"`

**教训：**
- Windows 桌面快捷方式涉及中文路径时，**优先用 VBS（UTF-16 LE）而非 BAT**
- BAT 只适合不含中文路径的场景，或项目路径全是英文的情况
- 不要依赖 `chcp 65001` 来解决 bat 文件本身的中文编码问题，它管不了 CMD 读文件阶段
- 验证 GBK bat 文件内容时，必须在 GBK 终端环境下查看，Git Bash（UTF-8）会显示乱码误导判断
