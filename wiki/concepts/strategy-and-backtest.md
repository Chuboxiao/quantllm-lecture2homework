# 策略引擎与回测为什么能复用接口

策略关心“收到什么数据”和“产生什么交易意图”。实盘引擎负责把意图交给网关，回测引擎用历史数据和撮合假设模拟结果。两者为模板提供相似的方法，因此同一策略可以复用主要逻辑。

源码入口：[CtaTemplate](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/template.py#L12)、[CtaEngine](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L69)、[BacktestingEngine](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L46)。

## 实盘侧的状态

- `inited` 表示初始化状态；`trading` 控制模板发单。
- 行情按合约路由到策略，成交按订单映射路由到策略。
- 本地停止单保存在策略引擎中，触发后转成实际委托。这不是服务器一直替你托管的订单，程序停止运行时不能期待本地触发逻辑继续运行。

来源：[CtaEngine.send_local_stop_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L393)、[CtaEngine.check_stop_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L220)。

## 回测侧的假设

在 `new_bar` 中先撮合已有订单，后调用 `on_bar`；策略刚从当前 Bar 生成的限价单不会在同一次已有订单撮合阶段被处理。

Bar 模式的限价撮合比较买价与最低价、卖价与最高价，触价后按实现确定成交价并整笔成交。它没有刻画“前面还有多少人排队”和“对手方只有几手”。因此这一回测只是特定执行假设下的结果。

来源：[BacktestingEngine.new_bar](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L649)、[BacktestingEngine.cross_limit_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L671)。

本轮没有历史数据实验，也没有证明任何示例策略盈利。后续研究要分别核实数据可用时点、交易成本及成交模型。

关联：[CTA 阅读笔记](../sources/vnpy-ctastrategy.md)、[因子研究入口](factor-research.md)。
