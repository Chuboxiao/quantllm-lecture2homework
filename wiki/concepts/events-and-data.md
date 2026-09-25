# 事件、回调与数据对象

“回调”是程序提前提供一个函数，等事情发生后由框架调用。例如行情到达时调用 `onRtnDepthMarketData`；无需自己不停问服务器“有新价格吗”。

`Event` 把事件类型与数据放在一起。`EventEngine.put` 入队，`register` 登记处理函数，工作线程取出消息并调用处理函数。当前实现由一个分发线程顺序执行处理函数；慢处理会拖延后续消息。来源：[EventEngine._process](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/event/engine.py#L66)。

| 对象 | 回答的问题 | 典型内容 |
|---|---|---|
| TickData | 刚收到什么行情？ | 最新价、盘口、累计量、时间 |
| BarData | 这一段时间价格怎样变化？ | 开高低收、区间成交量 |
| SubscribeRequest | 要看哪个合约？ | symbol、exchange |
| OrderRequest | 想怎样交易？ | 方向、开平、价格、数量 |
| OrderData | 这张订单现在怎样了？ | 状态、总量、累计成交量 |
| TradeData | 哪一笔实际成交了？ | 成交号、价格、数量、关联订单 |
| PositionData | 柜台报告持有什么？ | 方向、总量、冻结量、昨仓 |
| AccountData | 柜台报告还有多少钱？ | 余额、冻结、可用 |
| ContractData | 合约怎样报价和下单？ | 交易所、乘数、价格刻度、数量范围 |

来源：[vnpy/trader/object.py](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/object.py#L1)。`TickData` 不是“每一笔成交”的保证，也不是自己的成交回报；自己的成交使用 `TradeData`。

合约的标准标识 `vt_symbol = symbol + '.' + exchange`，订单标识 `vt_orderid = gateway_name + '.' + orderid`。这些组合帮助区分来源，不能随便把多个环境的数据混在一起。

`BaseGateway.on_tick` 会发通用行情事件及该合约的行情事件。若同一个业务同时订阅两种事件，就要避免重复处理。来源：[BaseGateway.on_tick](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/gateway.py#L93)。

老师说“超过价格下单”可以直接比较每次行情的最新价；若比较一分钟收盘价，才需要聚合 K 线。来源：[BarGenerator.update_tick](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/utility.py#L204)。

关联：[架构](architecture.md)、[订单与持仓](orders-and-positions.md)。
