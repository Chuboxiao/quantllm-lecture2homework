"""One reproducible round of moving-average factor research on AU0 daily data."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import json

import numpy as np
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/factor_research/au0_daily.csv"
REPORT = ROOT / "data/factor_research/au0_result.md"
URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V21052021_4_12=/InnerFuturesNewService.getDailyKLine"


def download() -> pd.DataFrame:
    response = requests.get(URL, params={"symbol": "AU0", "type": "2021_04_12"}, timeout=20)
    response.raise_for_status()
    body = response.text
    start, end = body.find("=("), body.rfind(");")
    if start < 0 or end <= start:
        raise ValueError("Unexpected Sina daily data response")
    rows = json.loads(body[start + 2:end])
    data = pd.DataFrame(rows).rename(columns={
        "d": "date", "o": "open", "h": "high", "l": "low", "c": "close",
        "v": "volume", "p": "open_interest", "s": "settlement",
    })
    DATA.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(DATA, index=False)
    return data


def load(refresh: bool) -> pd.DataFrame:
    data = download() if refresh or not DATA.exists() else pd.read_csv(DATA)
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    for field in ("open", "high", "low", "close", "volume", "open_interest", "settlement"):
        data[field] = pd.to_numeric(data[field], errors="raise")
    today = pd.Timestamp(datetime.now(ZoneInfo("Asia/Shanghai")).date())
    data = data.loc[data.date < today].sort_values("date").reset_index(drop=True)
    if len(data) < 500 or data.date.duplicated().any() or (data[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Insufficient, duplicate, or nonpositive daily prices")
    return data


def features(data: pd.DataFrame) -> pd.DataFrame:
    c = data.close
    m5, m10, m20, m40, m60 = (c.rolling(n, min_periods=n).mean() for n in (5, 10, 20, 40, 60))
    gap = m5 / m20 - 1
    ret = c.pct_change()
    slope5 = m5 / m5.shift(3) - 1
    slope20 = m20 / m20.shift(3) - 1
    candidates = {
        "短长均线偏离5_20": gap,
        "短长均线偏离10_40": m10 / m40 - 1,
        "短长均线偏离5_60": m5 / m60 - 1,
        "均线偏离3日变化": gap - gap.shift(3),
        "均线偏离10日变化": gap - gap.shift(10),
        "均线偏离3日加速度": gap - 2 * gap.shift(3) + gap.shift(6),
        "短均线3日斜率": slope5,
        "长均线10日斜率": m20 / m20.shift(10) - 1,
        "短长均线斜率差": slope5 - slope20,
        "过去10日短均线上方占比": (gap > 0).astype(float).rolling(10, min_periods=10).mean(),
        "波动率标准化均线偏离": gap / ret.rolling(20, min_periods=20).std(),
        "成交量确认均线偏离": gap * data.volume / data.volume.rolling(20, min_periods=20).mean(),
    }
    return pd.DataFrame(candidates).replace([np.inf, -np.inf], np.nan)


def evaluate(data: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    x = features(data)
    # A score formed after close t can first trade at open t+1; hold five trading days.
    target = data.open.shift(-6) / data.open.shift(-1) - 1
    full = pd.concat([data[["date"]], x, target.rename("next_5d_open_return")], axis=1).dropna()
    # The t+1 to t+6 holding windows are disjoint when signal dates are six rows apart.
    sample = full.iloc[::6].reset_index(drop=True)
    a, b = int(len(sample) * .6), int(len(sample) * .8)
    splits = {"训练": sample.iloc[:a], "验证": sample.iloc[a:b], "测试": sample.iloc[b:]}
    rows = []
    for name in x.columns:
        row = {"因子": name}
        for label, frame in splits.items():
            row[label + "样本"] = len(frame)
            row[label + "秩相关"] = frame[name].rank().corr(frame.next_5d_open_return.rank())
        rows.append(row)
    result = pd.DataFrame(rows)
    eligible = result.loc[(result["训练秩相关"] > 0) & (result["验证秩相关"] > 0)]
    selected = None if eligible.empty else eligible.sort_values("验证秩相关", ascending=False).iloc[0]["因子"]
    metadata = {
        "data_start": data.date.min().date().isoformat(),
        "data_end": data.date.max().date().isoformat(),
        "rows": len(data), "sample_rows": len(sample),
        "train_dates": (splits["训练"].date.min().date().isoformat(), splits["训练"].date.max().date().isoformat()),
        "validation_dates": (splits["验证"].date.min().date().isoformat(), splits["验证"].date.max().date().isoformat()),
        "test_dates": (splits["测试"].date.min().date().isoformat(), splits["测试"].date.max().date().isoformat()),
        "selected": selected,
        "sha256": sha256(DATA.read_bytes()).hexdigest(),
        "large_daily_jumps": int((data.open.pct_change().abs() > .1).sum()),
    }
    return result, metadata


def write_report(result: pd.DataFrame, m: dict) -> None:
    selected = m["selected"]
    selected_row = result.loc[result["因子"] == selected].iloc[0] if selected else None
    lines = [
        "# 第二部分作业报告：黄金期货均线动量因子", "",
        "## 问题与数据", "",
        "Clue：短均线相对长均线走强、持续或加速时，未来五个交易日收益是否更高？本轮预先构造 12 个候选，只运行一轮。它们是同一思路的变体，并非 12 个独立发现。", "",
        f"研究数据是新浪财经 AU0 黄金期货连续合约日线，共 {m['rows']} 日（{m['data_start']} 至 {m['data_end']}）。使用 [AKShare 接口文档](https://github.com/akfamily/akshare/blob/main/docs/data/futures/futures.md) 所列的 [Sina 日线接口](https://github.com/akfamily/akshare/blob/main/akshare/futures/futures_zh_sina.py)。本地原始 CSV 位于 `data/factor_research/au0_daily.csv`，不上传；SHA-256：`{m['sha256']}`。", "",
        "## 评价约定", "",
        "每个因子只使用截至交易日 t 收盘已知的日线。标签为 t+1 开盘到 t+6 开盘的收益，避免在算出收盘因子后又假定能在同一收盘价成交。每六行取一行，使五日持有窗口互不重叠；样本按时间先后拆为训练 60%、验证 20%、测试 20%。评价指标为因子分数与未来收益的 Spearman 秩相关，正数支持所提的同向假设。", "",
        f"非重叠样本共 {m['sample_rows']} 个：训练 {m['train_dates'][0]}—{m['train_dates'][1]}，验证 {m['validation_dates'][0]}—{m['validation_dates'][1]}，测试 {m['test_dates'][0]}—{m['test_dates'][1]}。只在训练和验证秩相关都为正时，按验证秩相关选出候选；测试数据仅用于最后审计，不据此修改公式。", "",
        "| 候选因子 | 训练 IC | 验证 IC | 测试 IC |", "|---|---:|---:|---:|",
    ]
    for _, row in result.iterrows():
        lines.append(f"| {row['因子']} | {row['训练秩相关']:+.3f} | {row['验证秩相关']:+.3f} | {row['测试秩相关']:+.3f} |")
    lines += ["", "## 结果与限制", ""]
    if selected_row is None:
        lines.append("12 个候选中没有一个在训练期和验证期都呈正相关；本轮没有选出可保留的因子。测试期结果只作一次性审计，不能反过来挑公式。")
    else:
        lines.append(f"按预定规则选出 **{selected}**；它的训练/验证/测试 IC 依次为 {selected_row['训练秩相关']:+.3f}、{selected_row['验证秩相关']:+.3f}、{selected_row['测试秩相关']:+.3f}。这只是历史预测关联，不等于可交易利润。")
    lines += [
        "", f"日线中相邻开盘价变动超过 10% 的次数为 {m['large_daily_jumps']}，可能含真实行情或主力合约切换。AU0 的连续合约拼接与复权规则未经交易所核验；本研究也未扣除手续费、滑点或换月成本，只有一个标的，不能据此认定稳定收益。反复筛选 12 个相近公式可能放大验证期偶然性。", "",
        "复现：在项目根目录安装 `pandas numpy requests` 后运行 `python projects/factor_research/run.py --refresh`；离线复核可省略 `--refresh` 使用本地缓存。", "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Download a fresh public AU0 daily CSV")
    args = parser.parse_args()
    data = load(args.refresh)
    result, metadata = evaluate(data)
    write_report(result, metadata)
    print(f"Wrote {REPORT}; selected={metadata['selected']}; samples={metadata['sample_rows']}")


if __name__ == "__main__":
    main()
