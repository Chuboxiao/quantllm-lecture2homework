# 因子研究

## 新授权的均线＋价格组合研究

`ma_price_research.py` 及三个分轮脚本对多层均线、日内开高低收、跳空和成交量做了四轮探索，预列候选数依次为 10、12、12、15（含重复对照）。没有发现符合独立检验要求的理想因子；全部指标与限制见[第二部分综合报告](../../reports/第二部分作业报告.md)。现有 `reports/ma_price/` 拒绝覆盖，复现时为 `--out` 指定新的空目录：

```bash
.venv/bin/python projects/factor_research/ma_price_research.py --stage plan --round 1 --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/ma_price_research.py --stage run --round 1 --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/test_ma_price_research.py
.venv/bin/python projects/factor_research/ma_price_round2.py --stage plan --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/ma_price_round2.py --stage run --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/ma_price_round3.py --stage plan --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/ma_price_round3.py --stage run --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/ma_price_round4.py --stage plan --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/ma_price_round4.py --stage run --out /tmp/pku-ma-price-reproduce
.venv/bin/python projects/factor_research/audit_ma_price_round.py --round 3 --out /tmp/pku-ma-price-reproduce/round_03_diagnostic.json
.venv/bin/python projects/factor_research/audit_ma_price_round.py --round 4 --out /tmp/pku-ma-price-reproduce/round_04_diagnostic.json
```

唯一通过历史初筛的第一轮公式已在中证500行情下载前锁定。原始数据留在 Git 忽略目录，下载可按股票续传；转移检查已只运行一次，结果**未通过**，保存在 `reports/ma_price/transfer_result.json`。相同年份的不同股票池不是新的未来日期。下列命令用于在新的空目录准备数据；原检验脚本会拒绝覆盖现有结果：

```bash
.venv/bin/python projects/factor_research/fetch_csi500_transfer.py --phase members
.venv/bin/python projects/factor_research/fetch_csi500_transfer.py --phase bars --workers 3
.venv/bin/python projects/factor_research/audit_ma_price_transfer.py
```

最终候选 `close_lower_half` 另在**已经看过结果**的同一中证500数据上做了一次事后诊断，见 `reports/ma_price/reused_csi500_final_diagnostic.json`；它不计作新的独立测试，脚本 `audit_ma_price_reused_csi500.py` 拒绝覆盖既有结果。未来真正新时段的公式和判据已保存在 `reports/ma_price/final_candidate_lock.json`，所需行情尚未存在。

## 同一来源的沪深300历史数据

`download_csi300_history.py` 通过匿名 BaoStock 接口下载交易日历、2008 年以来每周首个交易日的历史成分快照，以及所有曾入选股票从 2007-09 起的前复权日线；部分年份的老师缓存与 BaoStock 历史成分不一致，故新数据独立保存，不覆盖旧研究。原始数据位于 Git 忽略的 `data/factor_research/baostock_csi300_history/`，其中 `.parts/` 用于中断续传。命令：

```bash
.venv/bin/python projects/factor_research/download_csi300_history.py --workers 3
```

完成后读取 `manifest.json` 的覆盖和 SHA-256；`membership_weekly.parquet` 是**每周快照**，不能当作已逐日核实的精确历史成员资格。任意日的正式因子信号仍应在该日查询并保存成分。`bars_qfq.parquet` 适合均线比例研究，但前复权价格不等于真实委托价，也未验证涨跌停可成交性。2026 年此前已被查看，不因重下载而成为新的独立测试。

用户授权的统一数据延伸研究另用 `--phase signal-members` 匿名查询每隔六个市场交易日的**准确当日**沪深300成分，保存在 `membership_signal_days.parquet`。先固定 12 个候选和评价方法，再计算并保存所有结果；全部日期均为已看过的历史探索，结论见[第二部分综合报告](../../reports/第二部分作业报告.md)：

```bash
.venv/bin/python projects/factor_research/download_csi300_history.py --workers 2 --phase signal-members
.venv/bin/python projects/factor_research/ma_unified_research.py --stage plan
.venv/bin/python projects/factor_research/ma_unified_research.py --stage run
.venv/bin/python projects/factor_research/audit_ma_unified_sampling.py
.venv/bin/python projects/factor_research/audit_ma_unified_sampling.py --all-offsets
```

`plan`、`run` 和两份审计各自拒绝覆盖已有结果；复现时给研究及审计命令都传入相同的新 `--out` 目录，或只读查看现有 JSON。采样审计是看过结果后的稳健性检查，不能用于挑选表现最好的起点。

旧 `market_down_day` 因子另做了 2024—2026 年**全交易日**事后检查，使用前次固定 300 股数据和原公式，按 10／20 个交易日区块估计重叠五日收益的不确定性。结果见 `reports/ma_unified/dense_day_audit.json`，此命令拒绝覆盖现有结果：

```bash
.venv/bin/python projects/factor_research/audit_ma_dense_days.py
```

## 股票数据核查

`audit_stock_cache.py` 读取老师下载包中的 Arrow 数据和历史成分区间，核查覆盖、重复、异常值及成分匹配；不运行老师的项目或交易代码。依赖 `polars`。在项目根目录运行：

```bash
.venv/bin/python projects/factor_research/audit_stock_cache.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache"
```

输出为 `reports/stock-data-audit.json`。程序只解析基础 pickle 的内嵌 Arrow 字节；小型成分缓存限制可加载的对象类型。原始附件不修改、不复制到仓库。

## 股票因子实验（第二项作业）

独立实现见 `stock_round.py`。使用核查过的历史成分，按当时成员筛选；一次计算同股未来五日收益与同日横截面排名。四轮各 12 个候选，完整结果见 `reports/stock_factors/`，结论见[第二部分报告](../../reports/第二部分作业报告.md)。测试期平均信号收益为负，没有保留可交易因子。

若取得相同 SHA-256 的老师缓存，可以依次执行下面的命令。`--output-dir` 应指定空目录，防止覆盖已保存的结果；本机已生成的报告目录会阻止重复探索。

```bash
.venv/bin/python projects/factor_research/stock_round.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 1 --output-dir /tmp/pku-factor-reproduce
.venv/bin/python projects/factor_research/stock_round.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 2 --output-dir /tmp/pku-factor-reproduce
.venv/bin/python projects/factor_research/stock_round.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 3 --output-dir /tmp/pku-factor-reproduce
.venv/bin/python projects/factor_research/stock_round.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 4 --output-dir /tmp/pku-factor-reproduce
.venv/bin/python projects/factor_research/stock_round.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage finalize --output-dir /tmp/pku-factor-reproduce
```

需要 `polars`。下载包原始股票数据没有提交到 GitHub；没有该缓存只能阅读程序及保存的指标，无法重新计算。本程序只做预测统计，不连接 SimNow，不做股票实盘回测。

## 均线线索再研究（2026-09-24）

继上述未通过测试的实验，`ma_followup.py` 又运行四轮各 12 个均线条件候选。探索只用老师缓存的 2008—2020 年，2021—2023 年已在上一轮被看过而不再用于筛选。`fetch_ma_holdout.py` 通过匿名 BaoStock 连接取得一个在 2023-12-29 固定的 300 股样本的 2024—2025 年前复权日线；不会登录 SimNow 或发单。数据存于 Git 忽略的 `data/factor_research/`；摘要与 SHA-256 存于 `reports/ma_followup_data.json`。结论见[第二部分综合报告](../../reports/第二部分作业报告.md)。

在项目根目录运行；先安装 `polars`、`baostock==0.9.4`。复现研究时请给 `--output-dir` 指定**新的空目录**，避免覆盖本次的一次性测试记录：

```bash
.venv/bin/python projects/factor_research/fetch_ma_holdout.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache"
.venv/bin/python projects/factor_research/ma_followup.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 1 --output-dir /tmp/pku-ma-reproduce
.venv/bin/python projects/factor_research/ma_followup.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 2 --output-dir /tmp/pku-ma-reproduce
.venv/bin/python projects/factor_research/ma_followup.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 3 --output-dir /tmp/pku-ma-reproduce
.venv/bin/python projects/factor_research/ma_followup.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 4 --output-dir /tmp/pku-ma-reproduce
.venv/bin/python projects/factor_research/ma_followup.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage finalize --output-dir /tmp/pku-ma-reproduce
```

每轮结果保留完整候选；一旦该输出目录有 `final.json`，脚本拒绝再开启探索。下载脚本会用 Git 忽略的逐股票缓存续传；测试完成后可删除该缓存，只留 Parquet 和报告。再次下载 BaoStock 行情可能因历史数据修订或复权基准改变而与本次 SHA-256 不同。

## 已完成的黄金初筛

运行 `run.py` 下载或读取新浪财经 AU0 连续合约日线，计算 12 个长短期均线相关候选，并按时间分割报告训练、验证、测试期秩相关。数据缓存和该练习生成的 Markdown 均保存在 Git 忽略的 `data/factor_research/`；概要见[第二部分综合报告](../../reports/第二部分作业报告.md)。

在项目根目录运行：

```bash
.venv/bin/python projects/factor_research/run.py --refresh
```

只用本地缓存重新计算时省略 `--refresh`。需要 `pandas`、`numpy`、`requests`。本轮没有同时通过训练与验证的正相关候选，不把测试期偶然的正值当成发现。

## 去掉事后筛选后的继续研究（2026-09-24）

`ma_clean_research.py` 在前两次股票研究后，进一步做四轮各 12 个候选。它只用信号日可知的条件入样；未来没有买入的信号记为收益 0，已买入却不能按期退出的持仓按最近可见收盘价标记，另报告 −100% 压力值，均不删除该信号。每天从正分股票中取分数最高的至多 20 只。2008—2023 年老师缓存和已看过的 2024—2025 年 BaoStock 数据用于开发，2026 年表现直到 `lock` 选出一个候选后才看。四轮均无完全合格因子；一次诊断检验也未达到“理想”规则。详情见[第二部分综合报告](../../reports/第二部分作业报告.md)。

下载时通过匿名 BaoStock 接口使用 2023-12-29 固定的 300 股名单，不连接任何交易账号。运行环境为 Python 3.12、Polars 1.44.2、BaoStock 0.9.4。复现时给 `--output-dir` 一个空目录；保留 `lock` 和 `finalize` 两个阶段以防在测试数据上反复改公式：

```bash
.venv/bin/python projects/factor_research/fetch_ma_holdout.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --begin 2023-09-01 --end 2026-09-23 --out data/factor_research/ma_research_2026.parquet --summary reports/ma_research_2026_data.json
.venv/bin/python projects/factor_research/ma_clean_research.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 1 --output-dir /tmp/pku-ma-clean-reproduce
.venv/bin/python projects/factor_research/ma_clean_research.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 2 --output-dir /tmp/pku-ma-clean-reproduce
.venv/bin/python projects/factor_research/ma_clean_research.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 3 --output-dir /tmp/pku-ma-clean-reproduce
.venv/bin/python projects/factor_research/ma_clean_research.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage explore --round 4 --output-dir /tmp/pku-ma-clean-reproduce
.venv/bin/python projects/factor_research/ma_clean_research.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage lock --output-dir /tmp/pku-ma-clean-reproduce
.venv/bin/python projects/factor_research/ma_clean_research.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache" --stage finalize --output-dir /tmp/pku-ma-clean-reproduce
```

再次下载历史行情可能因提供者修订而得到不同的文件指纹；如果数据指纹或研究脚本在 `lock` 后发生变化，`finalize` 会拒绝运行。`test_ma_clean_research.py` 核对未来缺行不会让既有信号消失。

测试后发现原脚本的训练／验证段最后一个信号日可能在下一段退出。为保留锁定的研究脚本与一次性测试证据，没有改写原四轮文件；`audit_ma_boundary.py` 只用开发期数据重算严格期末边界。其[审计结果](../../reports/ma_clean/boundary_audit.json)显示合格因子仍为 0，诊断候选不变。运行命令：

```bash
.venv/bin/python projects/factor_research/audit_ma_boundary.py "/老师下载包路径/pku_demo/projects/alpha_mining_demo/runs/cache"
```
