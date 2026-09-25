# CTP 从连接到收到行情

连接是网络层成功，登录是账号获准访问，订阅是请求特定合约，收到持续更新才是行情链路可用。这四个阶段分别记录，不能合并成一句“连接成功”。

## 行情路线

1. 创建底层 API，注册行情前置地址，启动 API。
2. 收到 `onFrontConnected` 后发 `reqUserLogin`。
3. 在 `onRspUserLogin` 检查 `ErrorID`，成功后请求订阅。
4. `onRspSubMarketData` 告诉你订阅请求是否出错。
5. `onRtnDepthMarketData` 持续带来行情；记录合约、价格、行情时间和本地接收时间。
6. 断线时清理就绪状态；重连并登录后恢复订阅。

来源：[CtpMdApi.onFrontConnected](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L270)、[CtpMdApi.onRspUserLogin](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L280)、[CtpMdApi.subscribe](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L403)。

## 交易路线

连接 → 根据环境认证 → 登录 → 结算确认 → 合约查询，以及资金、持仓查询。订单请求发出后，状态和成交继续通过异步回报进入。

来源：[CtpTdApi.onRspUserLogin](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L479)、[CtpTdApi.onRspSettlementInfoConfirm](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L526)、[CtpTdApi.onRspQryInstrument](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L612)。

## 为什么只连行情有时还看不到标准 TickData

完整 `CtpGateway` 会在处理行情时查 `symbol_contract_map`。如果交易通道尚未查回合约信息，行情会被过滤。底层 `MdApi` 回调直接拿原始字典，适合老师的最小打印 Demo；但你需要自己处理字段、异常值和时间。

这条区别来自 [CtpMdApi.onRtnDepthMarketData](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L302)，不是猜测网络是否正常。

SimNow 网站登录状态与 Python 接口登录是两回事。本轮未读取浏览器账号、未连接 SimNow；服务器地址、环境参数和合约代码都要在实际接入时核实。

关联：[CTP 源码](../sources/vnpy-ctp.md)、[Demo 准备](../code/ctp-demo-plan.md)。
