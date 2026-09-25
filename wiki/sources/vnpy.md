# vnpy：交易系统的共同基础

版本：`fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09`。本轮重点阅读事件、主引擎、网关契约、标准数据对象及相关工具；不声称逐行审计整个仓库。

## 作用

它定义行情、订单、成交等对象，并把网关发来的消息交给订单缓存和策略等模块。你可以把它理解为各模块共同使用的“数据格式和通信规则”。

| 入口 | 本轮核对的行为 |
|---|---|
| [EventEngine](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/event/engine.py#L33) | 用队列接收事件，用工作线程按类型分发；另有定时线程 |
| [MainEngine](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L81) | 启动事件引擎，注册网关和功能引擎，按网关名称转发请求 |
| [OmsEngine](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L360) | 缓存最新行情、订单、成交、账户、持仓、合约及活动订单 |
| [BaseGateway](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/gateway.py#L33) | 规定 connect、subscribe、send_order 等接口和标准事件回报 |
| [vnpy/trader/object.py](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/object.py#L1) | 定义 TickData、OrderData、TradeData 等对象和组合标识符 |
| [PositionHolding](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/converter.py#L17) | 根据今昨仓和冻结量处理开平仓转换 |
| [BarGenerator.update_tick](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/utility.py#L204) | 把 tick 聚合成分钟 K 线；阈值策略不一定需要它 |

## 一笔消息怎样走

网关产生 `TickData` → `BaseGateway.on_tick` 发事件 → `EventEngine` 分发 → `OmsEngine` 更新最新价格，策略引擎调用相应策略。

下单方向相反：策略生成 `OrderRequest` → `MainEngine.send_order` 选择网关 → 网关调用外部接口。这个转发函数不是一套完整的资金与风险审查器；自己写 Demo 时仍要定义必要限制。

## 容易误解的地方

- OMS 在这里主要是内存缓存和开平转换入口，并不自动形成完整的持久化审计账本。
- `orders` 和 `trades` 是不同字典。一笔订单可以对应多笔成交。
- `MainEngine` 创建时已启动事件引擎，不应再对同一个事件引擎重复启动。
- `MainEngine` 会改变当前工作目录；见[环境准备](../code/mac-environment.md)，配置路径不能只凭启动终端的位置猜测。
- 当前依赖中包含 Qt 相关库。不配置图形界面，仍可能因为包依赖而安装这些库。

继续阅读：[系统架构](../concepts/architecture.md)、[事件与数据](../concepts/events-and-data.md)、[订单与持仓](../concepts/orders-and-positions.md)。
