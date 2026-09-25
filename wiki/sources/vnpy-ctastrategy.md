# vnpy_ctastrategy：单标的策略怎样运行

版本：`6ef76981624bf55b2ea978f8587f74d633aafc72`，包版本 `1.4.1`。本轮重点阅读模板、实盘引擎、回测撮合路径和双均线示例，未运行历史回测。

## 模板、引擎和策略实例

[CtaTemplate](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/template.py#L12) 规定 `on_init`、`on_start`、`on_tick`、`on_bar`、`on_order`、`on_trade` 等入口，并维护 `inited`、`trading` 和 `pos`。

[CtaEngine](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L69) 管理策略实例、合约到策略的映射、订单到策略的映射，并监听行情、委托和成交事件。

- `process_tick_event` 按合约找到已初始化策略，再调用 `on_tick`。
- `CtaTemplate.send_order` 只有在 `trading` 为真时才转发请求。
- `process_trade_event` 用成交标识过滤重复推送，再更新策略 `pos`，随后调用 `on_trade`。
- `start_strategy` 先执行 `on_start`，再将 `trading` 设为真；不要想当然地认为 `on_start` 中可以正常通过模板发单。

证据：[CtaEngine.process_trade_event](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L193)、[CtaTemplate.send_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/template.py#L227)、[CtaEngine.start_strategy](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L708)。

## 下单的四种含义

| 方法 | 方向与开平 | 含义 |
|---|---|---|
| buy | LONG + OPEN | 买入开多仓 |
| sell | SHORT + CLOSE | 卖出平多仓 |
| short | SHORT + OPEN | 卖出开空仓 |
| cover | LONG + CLOSE | 买入平空仓 |

这是模板定义的语义。只说“买/卖”不能完整表达期货委托。引擎还会按合约最小刻度取整，并通过开平转换器处理委托。

## 从示例看策略逻辑

[DoubleMaStrategy](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/strategies/double_ma_strategy.py#L15) 的 `on_tick` 调用 `BarGenerator`，`on_bar` 把 K 线送进 `ArrayManager`，数据足够时比较快慢均线交叉，再调用买卖方法。

这是学习结构的例子，不是已验证能盈利的策略，也不是第一份 Demo 必须复制的逻辑。

## 同一策略怎样回测

[BacktestingEngine.new_bar](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L649) 先撮合已有订单，再把这根 K 线交给策略。[BacktestingEngine.cross_limit_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L671) 在 Bar 模式用高低价判断是否触价，满足条件时将整笔订单记成成交；它不模拟完整盘口排队和深度。

因此共享策略接口不代表回测成交与仿真成交完全相同。继续阅读[策略与回测](../concepts/strategy-and-backtest.md)。
