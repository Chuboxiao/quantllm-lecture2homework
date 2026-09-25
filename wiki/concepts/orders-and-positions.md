# 下单、订单状态与持仓

“我想买”“请求发出”“订单被受理”“已经成交”是不同事件。来源：[CtpTdApi.send_order](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L810)、[CtpTdApi.onRtnOrder](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L659)、[CtpTdApi.onRtnTrade](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L721)。

## 状态和数量

`OrderData` 保存原始委托量 `volume` 和累计成交量 `traded`；每笔 `TradeData.volume` 是该笔成交数量。`SUBMITTING`、`NOTTRADED`、`PARTTRADED` 被视为活动状态；已成交、已撤和拒绝不在活动状态集合。来源：[OrderData](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/object.py#L112)。

教学例子：买入 3 手，先成交 1 手，再成交 2 手。订单累计成交从 0 → 1 → 3；收到的两笔成交数量是 1 和 2。不能把订单累计数量再逐条累加成 4。

撤单发出只是请求，仍要等回报。发单超时也不能立刻重发，否则可能重复建立订单。

## CTA 策略持仓和账户持仓

CTA 的 `strategy.pos` 按归属于该策略的成交更新，并在调用 `on_trade` 前更新。它是该策略的净持仓变量，不自动等同于整个账户的全部多空持仓。来源：[CtaEngine.process_trade_event](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L193)。

柜台持仓通过持仓查询回报转换成 `PositionData`，OMS 再缓存它。CTA 的成交去重不能被解释为所有层都已经保证了幂等：OMS 的成交字典覆盖同键后仍会调用转换器，底层 Demo 要自行定义成交去重和恢复方案。来源：[OmsEngine.process_trade_event](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L416)。

期货还区分开仓、平仓、平今、平昨。`PositionHolding` 维护今昨仓及冻结量，在部分交易所场景会把平仓拆成不同请求。来源：[PositionHolding.convert_order_request_shfe](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/converter.py#L168)。

## 阈值策略的两个价格

触发价决定何时产生交易意图；限价决定最高愿买入或最低愿卖出多少。比如“最新价超过 3500 时触发”，不等于保证按 3500 成交。示例数值不代表推荐合约或交易参数。

需要明确只触发一次、首次启动已超阈值时是否触发，以及拒单后是否允许重新触发。避免每条满足条件的行情都再发一单。

关联：[Demo 准备](../code/ctp-demo-plan.md)、[CTA 模块](../sources/vnpy-ctastrategy.md)。
