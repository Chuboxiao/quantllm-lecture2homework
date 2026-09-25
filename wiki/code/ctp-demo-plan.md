# CTP 终端 Demo 的准备与实施顺序

状态（2026-09-24）：环境与底层终端 Demo 已完成。个人账号的行情、账户预检、价格触发开仓、60 秒自动平今和最终空仓均已在 SimNow 验收，见 [报告](../../reports/第一部分作业报告.md) 和 [最终规则](../../reports/第一部分作业报告.md)。本页保留实施过程的学习顺序。

## 采用老师的底层 API 路线

使用 `vnpy_ctp.api.MdApi` 和 `TdApi` 的 Python 子类处理回调。先持续打印行情，再增加交易状态与价格触发。第一版不依赖完整 CTA 策略引擎，不配置图形界面。

参考：[vnpy_ctp/api/__init__.py](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/api/__init__.py#L1)、[CtpMdApi](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L248)、[CtpTdApi](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L419)。直接继承底层接口时，要自行承担网关原本提供的字段清洗和状态处理。

## 分阶段验证

| 阶段 | 实现内容 | 完成证据 |
|---|---|---|
| 环境 | 独立 Python 环境，编译 CTP | 包版本记录，MdApi/TdApi 可导入 |
| 行情 | 登录、订阅、持续打印、退出清理 | 登录/订阅回报，多条带时间的真实仿真行情 |
| 交易准备 | 认证、登录、结算确认、合约/账户/持仓信息 | 分阶段成功回报，不凭请求返回值推断 |
| 触发规则 | 合约、阈值、比较方式、委托价、数量、一次触发 | 本地规则验证和清晰配置 |
| 仿真委托 | 发送、订单状态、成交、撤单与异常处理 | SimNow 实际回报及可对应的订单标识 |

## 程序组织建议

保持最小结构：入口负责读取配置、启动和退出；MD 类负责行情；TD 类负责交易；触发状态机负责一次触发与在途订单。账号配置留在 `configs/local/`，报告只保留脱敏证据。

价格规则需要明确是“高于阈值持续有效”还是“从阈值以下向上穿越”。本次最终使用前者，要求两条不同时间戳的有效行情都高于风控就绪后固定的阈值；只发一次，已有订单意图时拒绝重启再发。

下单前检查连接/登录就绪、有效新鲜行情、合约价格刻度、数量、已有触发或在途委托。先设计请求失败、拒单、部分成交、断线和重复成交的处理；用户已给出的授权持续有效，不重复索取同一权限。

`reqOrderInsert` 返回 0、拿到本地订单号、柜台受理、实际成交分开记录。未知状态时先查明，不盲目重发。来源：[CtpTdApi.send_order](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/vnpy_ctp/gateway/ctp_gateway.py#L810)。

## 下一次开始前的清单

- 检查当前 Python、编译器及包版本，选择可兼容版本组合。
- 检查 SimNow 环境地址、服务时间和接口模式。
- 由用户在本地配置个人 InvestorID 等信息，避免打印密码。
- 核实当前有效且有更新的合约，先完成持续行情。

关联：[环境准备](mac-environment.md)、[连接生命周期](../concepts/ctp-lifecycle.md)、[订单与持仓](../concepts/orders-and-positions.md)。
