# vnpy_ctp：把 CTP 连接到 Python 和 VeighNa

版本：`ad76250cf87cf5b03604336fde8c7489bdc0d0d7`，包声明 `6.7.11.4`。本轮阅读网关主文件、绑定导出、MD 数据转换、TD 请求入口、README 与构建配置；未编译或联网运行。

## 两层接口

`vnpy_ctp.api.MdApi` / `TdApi` 是 C++ 扩展暴露给 Python 的底层接口；`CtpMdApi` / `CtpTdApi` 是在其上实现 VeighNa 数据转换和流程的 Python 子类；`CtpGateway` 把这两者组合起来。

入口：[vnpy_ctp/api/__init__.py](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/api/__init__.py#L1)、[CtpGateway](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L135)、[CtpMdApi](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L248)、[CtpTdApi](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L419)。

## 行情通道

`createFtdcMdApi` 建立 API 对象，`registerFront` 指定前置地址，`init` 启动连接。连接回调 `onFrontConnected` 中发登录请求；成功回调中恢复订阅；行情通过 `onRtnDepthMarketData` 持续进入。

[CtpMdApi.onRtnDepthMarketData](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L302) 读取 `InstrumentID`、`LastPrice`、买卖档位、时间等字段，处理部分异常值，构造 `TickData`。该函数会丢弃没有时间戳或尚无合约缓存的行情。因此完整网关路线还依赖 TD 查询合约。

直接继承底层 `MdApi` 时，能先打印原始字典；这不会自动获得完整网关的字段清洗、合约缓存和事件分发，需要自己定义。具体 C++ 到字典的转换见 [vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp#L1) 中 `processRtnDepthMarketData`。

## 交易通道

[CtpTdApi.onFrontConnected](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L452) 在有认证码时先认证，再登录；登录成功后发结算确认；收到结算确认回调后查询合约。`onRspQryInstrument` 填充合约信息，并在查询完成后处理暂存的订单/成交回报。

[CtpTdApi.send_order](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L810) 把标准委托转换为 CTP 字段，调用 `reqOrderInsert`。非零返回值表示发送失败；返回订单号仍不等于成交，后续 `onRtnOrder`、`onRtnTrade` 才提供状态与成交事实。

订单号由 `FrontID_SessionID_OrderRef` 组合，成交回报利用 `OrderSysID` 映射关联订单。直接底层实现也要处理标识和回报次序，不能只打印一句“下单成功”。

## 本轮发现与实现提醒

- 同一实例重复创建底层连接可能出错；沿用回调驱动流程。
- 网关 `onRspSettlementInfoConfirm` 会直接写成功日志并发查询；自己的 Demo 应实际检查错误字段，并给重试设边界。
- `onRtnTrade` 通过已知 `OrderSysID` 直接取映射；Demo 应考虑恢复或消息顺序尚未建立映射的情况。
- `production_mode` 是接口环境参数，不能只凭“SimNow 是模拟盘”就推断它必须为 False；接入时核对服务器环境说明。
- Mac 要编译 C++ 扩展；[meson.build](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/meson.build#L1) 和 [pyproject.toml](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/pyproject.toml#L1) 才是本地版本的构建依据。

继续阅读：[连接生命周期](../concepts/ctp-lifecycle.md)、[订单与持仓](../concepts/orders-and-positions.md)、[Demo 准备说明](../code/ctp-demo-plan.md)。
