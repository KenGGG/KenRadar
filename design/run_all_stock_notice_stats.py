#!/usr/bin/env python3
"""
全 A 股（上交所 + 深交所，不含北交所）近两年公告数量统计
========================================================================
用法：

    cd /data/Projects/KenRadar
    conda activate openclaw
    python3 design/run_all_stock_notice_stats.py

输出文件：
    design/A股全量_近两年公告统计.md

中途中断可重新运行，会自动从断点继续：
    /tmp/all_a_stock_stats.jsonl
"""

import asyncio
import json
import os
import signal
import sys
import time
from datetime import date, timedelta

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kenradar.company_research.akshare_provider import (
    normalize_symbol, StockInfo, security_code, compact_date,
)

# ── 参数 ──────────────────────────────────────────────────────
CONCURRENCY = 8
CHECKPOINT = "/tmp/all_a_stock_stats.jsonl"
OUTPUT_MD = "design/A股全量_近两年公告统计.md"

today = date.today()
begin = (today - timedelta(days=365 * 2)).isoformat()
end = today.isoformat()

# ── 全局 ──────────────────────────────────────────────────────
queried_count = 0
error_count = 0
start_time = time.time()
stop_requested = False
_last_progress_len = 0


def handle_sigint(sig, frame):
    global stop_requested
    print("\n\n⚠️  保存检查点后退出...\n", flush=True)
    stop_requested = True


signal.signal(signal.SIGINT, handle_sigint)


def _show_progress(done_ok, done_err, total):
    """在同一行刷新进度。"""
    global _last_progress_len
    elapsed = time.time() - start_time
    done_total = done_ok + done_err
    rate = done_ok / max(elapsed, 0.1)
    pct = (done_total / total) * 100 if total > 0 else 100
    remaining = total - done_total
    eta = remaining / max(rate, 0.01)

    bar_len = 30
    filled = int(bar_len * done_total / max(total, 1))
    bar = "█" * filled + "░" * (bar_len - filled)

    line = (
        f"  [{bar}] {pct:5.1f}%  "
        f"{done_total:5d}/{total}  "
        f"✓{done_ok:4d}  ✗{done_err:3d}  "
        f"{elapsed:4.0f}s  "
        f"{rate:4.1f}只/s  "
        f"ETA {eta:4.0f}s"
    )
    sys.stdout.write("\r" + " " * _last_progress_len + "\r")
    sys.stdout.write(line)
    sys.stdout.flush()
    _last_progress_len = len(line)


# ═══════════════════════════════════════════════════════════════
# 第一步：获取股票列表
# ═══════════════════════════════════════════════════════════════

print("=" * 60)
print("获取 A 股股票列表（腾讯源 ak.stock_zh_a_spot）...")
print("=" * 60)
import akshare as ak

df = ak.stock_zh_a_spot()
print(f"  原始数据: {df.shape[0]} 只")

all_stocks = []
excluded_bj = 0
for _, row in df.iterrows():
    code = str(row.get("代码", "") or "").strip()
    name = str(row.get("名称", "") or "").strip()
    if not code:
        continue
    if code.startswith(("4", "8")) or code.startswith("920"):
        excluded_bj += 1
        continue
    try:
        sym = normalize_symbol(code)
        all_stocks.append(StockInfo(sym, name or sym))
    except ValueError:
        continue

print(f"  上交所 + 深交所: {len(all_stocks)} 只")
print(f"  排除北交所: {excluded_bj} 只")
print(f"  查询区间: {begin} ~ {end}（近 2 年）")
print()

# ═══════════════════════════════════════════════════════════════
# 第二步：并行查询公告数量
# ═══════════════════════════════════════════════════════════════

sem = asyncio.Semaphore(CONCURRENCY)
results: list[dict] = []


async def query_stock(stock: StockInfo) -> dict:
    """直接调 AKShare 接口，跳过 fetch_stock_info() 避免 SSL 超时损耗。"""
    async with sem:
        try:
            loop = asyncio.get_running_loop()
            def _fetch():
                code = security_code(stock.symbol)
                frame = ak.stock_individual_notice_report(
                    security=code,
                    symbol="全部",
                    begin_date=compact_date(begin),
                    end_date=compact_date(end),
                )
                return len(frame)
            count = await loop.run_in_executor(None, _fetch)
            return {"symbol": stock.symbol, "name": stock.name, "count": count}
        except Exception as e:
            return {"symbol": stock.symbol, "name": stock.name, "count": -1, "error": str(e)[:80]}


async def main():
    global queried_count, error_count

    # 加载检查点
    existing = set()
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT) as f:
            for line in f:
                r = json.loads(line)
                existing.add(r["symbol"])
                results.append(r)
                if r.get("count", -1) >= 0:
                    queried_count += 1
                else:
                    error_count += 1
        print(f"  从检查点恢复: {len(results)} 只")

    tasks = [query_stock(s) for s in all_stocks if s.symbol not in existing]
    total = len(tasks)
    if total == 0:
        print("  所有股票已查询完成！")
    else:
        print(f"  还需查询: {total} 只（并发 {CONCURRENCY}）")
    print()

    # 逐只处理，每完成一只立即更新进度（避免等一批100只才刷新）
    pending = asyncio.Queue()
    for t in tasks:
        await pending.put(t)

    async def worker():
        while not pending.empty() and not stop_requested:
            t = await pending.get()
            r = await t
            results.append(r)
            if r.get("error"):
                error_count += 1
            else:
                queried_count += 1
            _show_progress(queried_count, error_count, total)

    workers = [asyncio.create_task(worker()) for _ in range(CONCURRENCY)]
    await asyncio.gather(*workers)

    # 保存检查点
    with open(CHECKPOINT, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _show_progress(queried_count, error_count, total)
    print()

    if stop_requested:
        print("\n已中断，下次运行会自动恢复进度。")
        return

    # ═══════════════════════════════════════════════════════════
    # 第三步：生成 Markdown
    # ═══════════════════════════════════════════════════════════
    print()
    print("=" * 60)
    print("生成统计报告...")
    print("=" * 60)

    all_r = sorted(results, key=lambda r: r.get("count", 0), reverse=True)
    valid = [r for r in all_r if r.get("count", 0) >= 0]
    errored = [r for r in all_r if r.get("count", -1) < 0]
    total_notices = sum(r["count"] for r in valid)

    ranges = [
        ("0 条（无公告）", lambda c: c == 0),
        ("1 ~ 10 条", lambda c: 1 <= c <= 10),
        ("11 ~ 50 条", lambda c: 11 <= c <= 50),
        ("51 ~ 100 条", lambda c: 51 <= c <= 100),
        ("101 ~ 200 条", lambda c: 101 <= c <= 200),
        ("200 条以上", lambda c: c > 200),
    ]

    lines = []
    lines.append("# A 股全量 — 近两年公告统计\n")
    lines.append(f"**统计时间**: {today.isoformat()}")
    lines.append(f"**查询区间**: {begin} ~ {end}（近 2 年）")
    lines.append(f"**数据来源**: 东方财富 / AKShare（腾讯源获取股票列表）\n")
    lines.append("---\n")

    lines.append("## 总体概览\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| A 股总数（SH+SZ，不含北交所） | {len(all_r)} |")
    lines.append(f"| 成功查询 | {len(valid)} |")
    lines.append(f"| 查询失败 | {len(errored)} |")
    lines.append(f"| 公告总条数 | {total_notices:,} |")
    if valid:
        lines.append(f"| 平均每只股票公告数 | {total_notices / len(valid):.1f} |")
        lines.append(f"| 最多公告股票 | {valid[0]['name']} ({valid[0]['symbol']}) — {valid[0]['count']} 条 |")
        lines.append(f"| 最少公告股票 | {valid[-1]['name']} ({valid[-1]['symbol']}) — {valid[-1]['count']} 条 |")
    lines.append("")

    lines.append("## 公告数量分布\n")
    lines.append("| 范围 | 股票数 | 占比 |")
    lines.append("|------|--------|------|")
    for label, pred in ranges:
        n = sum(1 for r in valid if pred(r["count"]))
        lines.append(f"| {label} | {n} | {n / len(valid) * 100:.1f}% |")
    lines.append("")

    sh = [r for r in valid if ".SH" in r["symbol"]]
    sz = [r for r in valid if ".SZ" in r["symbol"]]
    lines.append("## 按交易所统计\n")
    lines.append("| 交易所 | 股票数 | 公告总数 | 平均 | 中位数 |")
    lines.append("|--------|--------|----------|------|--------|")
    for label, group in [("上交所 SH", sh), ("深交所 SZ", sz)]:
        counts = [r["count"] for r in group]
        avg = sum(counts) / len(counts) if counts else 0
        sorted_c = sorted(counts)
        med = sorted_c[len(sorted_c) // 2] if sorted_c else 0
        lines.append(f"| {label} | {len(group)} | {sum(counts):,} | {avg:.1f} | {med} |")
    lines.append("")

    topn = valid[:300]
    lines.append("## Top 300 公告最多的股票\n")
    lines.append("| 排名 | 股票代码 | 股票名称 | 近 2 年公告数 | 交易所 |")
    lines.append("|------|----------|----------|-------------|--------|")
    for idx, r in enumerate(topn, 1):
        ex = "上交所" if ".SH" in r["symbol"] else "深交所"
        lines.append(f"| {idx} | {r['symbol']} | {r['name']} | {r['count']} | {ex} |")
    lines.append("")

    lines.append("## 完整列表\n")
    lines.append("| 股票代码 | 股票名称 | 近 2 年公告数 |")
    lines.append("|----------|----------|-------------|")
    for r in all_r:
        c = str(r["count"]) if r["count"] >= 0 else f"ERR: {r.get('error', '')}"
        lines.append(f"| {r['symbol']} | {r['name']} | {c} |")

    lines.append(f"\n---\n*生成时间: {today.isoformat()}*")
    lines.append(f"*共查询 {len(all_r)} 只股票，成功 {len(valid)} 只，失败 {len(errored)} 只*")

    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n✅ 报告已保存到: {OUTPUT_MD}")
    print(f"   共 {len(all_r)} 只股票，成功 {len(valid)}，失败 {len(errored)}")
    print(f"   公告总条数: {total_notices:,}")
    print(f"   耗时: {time.time() - start_time:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
