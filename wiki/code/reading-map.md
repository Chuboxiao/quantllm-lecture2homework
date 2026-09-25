# 源码版本与阅读入口

本轮是围绕课堂任务的静态源码阅读，不是逐行全仓审计或运行验证。

| 仓库 | 固定提交 | 本地位置 |
|---|---|---|
| vnpy | [fa5206fe6383](https://github.com/vnpy/vnpy/tree/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09) | `raw/repos/vnpy` |
| vnpy_ctp | [ad76250cf87c](https://github.com/vnpy/vnpy_ctp/tree/ad76250cf87cf5b03604336fde8c7489bdc0d0d7) | `raw/repos/vnpy_ctp` |
| vnpy_ctastrategy | [6ef76981624b](https://github.com/vnpy/vnpy_ctastrategy/tree/6ef76981624bf55b2ea978f8587f74d633aafc72) | `raw/repos/vnpy_ctastrategy` |

vnpy 为稀疏检出，保留根文件与完整 `vnpy/` 源码目录；CTP 与 CTA 的浅克隆工作树完整。

## 已核对入口

下列链接指向固定版本中的定义行。本地同名文件可直接阅读；阅读范围侧重页面里解释的调用路径。

- vnpy：[EventEngine](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/event/engine.py#L33)
- vnpy：[MainEngine](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L81)
- vnpy：[OmsEngine](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L360)
- vnpy：[BaseGateway](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/gateway.py#L33)
- vnpy：[vnpy/trader/object.py](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/object.py#L1)
- vnpy：[PositionHolding](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/converter.py#L17)
- vnpy：[BarGenerator.update_tick](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/utility.py#L204)
- vnpy_ctp：[vnpy_ctp/api/__init__.py](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/api/__init__.py#L1)
- vnpy_ctp：[CtpGateway](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L135)
- vnpy_ctp：[CtpMdApi](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L248)
- vnpy_ctp：[CtpTdApi](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L419)
- vnpy_ctp：[CtpMdApi.onRtnDepthMarketData](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L302)
- vnpy_ctp：[vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp#L1)
- vnpy_ctp：[CtpTdApi.onFrontConnected](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L452)
- vnpy_ctp：[CtpTdApi.send_order](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L810)
- vnpy_ctp：[meson.build](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/meson.build#L1)
- vnpy_ctp：[pyproject.toml](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/pyproject.toml#L1)
- vnpy_ctastrategy：[CtaTemplate](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/template.py#L12)
- vnpy_ctastrategy：[CtaEngine](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L69)
- vnpy_ctastrategy：[CtaEngine.process_trade_event](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L193)
- vnpy_ctastrategy：[CtaTemplate.send_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/template.py#L227)
- vnpy_ctastrategy：[CtaEngine.start_strategy](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L708)
- vnpy_ctastrategy：[DoubleMaStrategy](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/strategies/double_ma_strategy.py#L15)
- vnpy_ctastrategy：[BacktestingEngine.new_bar](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L649)
- vnpy_ctastrategy：[BacktestingEngine.cross_limit_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L671)
- vnpy：[BaseGateway.on_tick](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/gateway.py#L93)
- vnpy：[MainEngine.send_order](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L254)
- vnpy_ctastrategy：[CtaEngine.process_tick_event](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L147)
- vnpy：[EventEngine._process](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/event/engine.py#L66)
- vnpy_ctp：[CtpMdApi.onFrontConnected](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L270)
- vnpy_ctp：[CtpMdApi.onRspUserLogin](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L280)
- vnpy_ctp：[CtpMdApi.subscribe](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L403)
- vnpy_ctp：[CtpTdApi.onRspUserLogin](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L479)
- vnpy_ctp：[CtpTdApi.onRspSettlementInfoConfirm](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L526)
- vnpy_ctp：[CtpTdApi.onRspQryInstrument](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L612)
- vnpy_ctp：[CtpTdApi.onRtnOrder](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L659)
- vnpy_ctp：[CtpTdApi.onRtnTrade](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L721)
- vnpy：[OrderData](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/object.py#L112)
- vnpy：[OmsEngine.process_trade_event](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L416)
- vnpy：[PositionHolding.convert_order_request_shfe](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/converter.py#L168)
- vnpy_ctastrategy：[BacktestingEngine](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/backtesting.py#L46)
- vnpy_ctastrategy：[CtaEngine.send_local_stop_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L393)
- vnpy_ctastrategy：[CtaEngine.check_stop_order](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/vnpy_ctastrategy/engine.py#L220)
- vnpy：[pyproject.toml](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/pyproject.toml#L1)
- vnpy_ctastrategy：[pyproject.toml](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/pyproject.toml#L1)
- vnpy_ctp：[README.md](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/README.md#L1)
- vnpy：[_get_trader_dir](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/utility.py#L38)
- vnpy：[MainEngine.__init__](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L86)
- vnpy_portfoliostrategy：[StrategyEngine](https://github.com/vnpy/vnpy_portfoliostrategy/blob/164d94f35e75c1b3c5c9a62f0b94de78e3e9662c/vnpy_portfoliostrategy/engine.py#L51)、[StrategyTemplate.rebalance_portfolio](https://github.com/vnpy/vnpy_portfoliostrategy/blob/164d94f35e75c1b3c5c9a62f0b94de78e3e9662c/vnpy_portfoliostrategy/template.py#L190)
- vnpy_spreadtrading：[SpreadEngine](https://github.com/vnpy/vnpy_spreadtrading/blob/5919a8ac06dce5a27ad485aaeef364e451e67dce/vnpy_spreadtrading/engine.py#L50)、[SpreadData.calculate_price](https://github.com/vnpy/vnpy_spreadtrading/blob/5919a8ac06dce5a27ad485aaeef364e451e67dce/vnpy_spreadtrading/base.py#L217)、[SpreadTakerAlgo](https://github.com/vnpy/vnpy_spreadtrading/blob/5919a8ac06dce5a27ad485aaeef364e451e67dce/vnpy_spreadtrading/algo.py#L21)

## 未覆盖范围

- UI、所有策略示例、整个 CTP SDK、所有自动生成的 TD 绑定未逐行审阅。
- 投组/价差已下载独立模块并阅读相关入口，但未安装或运行这两个应用。
- vnpy.alpha 仅检查依赖和位置；第二项作业使用自己的简明因子脚本，没有运行 vnpy.alpha。
- 本机已安装并运行 `vnpy_ctp` 底层接口，完成 SimNow 仿真开仓和平今；这不等于上述两个策略应用也已运行。

返回：[Wiki 目录](../index.md)。
