# 本地数据与交易账本

`factor_research/au0_daily.csv` 是新浪财经 AU0 黄金期货连续合约日线缓存；早期练习的结论见[第二部分报告](../reports/第二部分作业报告.md)。原始数据与 `run.py` 生成的本地 Markdown 均不纳入 Git，可用 `projects/factor_research/run.py --refresh` 重新下载和计算。

`factor_research/baostock_csi300_history/` 是匿名 BaoStock 下载的沪深300历史成分快照、研究信号日的准确成分、股票前复权日线、交易日历和基础信息；数据口径与核查结果见[第二部分报告](../reports/第二部分作业报告.md)，复现命令见[因子研究说明](../projects/factor_research/README.md)。`.parts/` 是断点缓存，整个目录不纳入 Git。

`trade_state/` 保存个人 SimNow 账号的订单意图和成交状态。它是防止断线、重启后重复发单的账本，**不要为重跑演示而删除**；该目录不纳入 Git。
