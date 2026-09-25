# CTP 终端行情 Demo

直接继承 `vnpy_ctp.api.MdApi` 和 `TdApi`，完成行情登录、交易认证与登录、结算确认、合约查询、行情订阅和持续打印。没有调用发单或撤单接口。

当前默认配置为个人账号。交易登录、持续行情和一次 1 手模拟开仓—自动平今均已通过；详见 [报告](../../reports/第一部分作业报告.md)。

## 运行

在“第二讲作业”根目录执行：

```bash
.venv/bin/python projects/ctp_demo/demo.py
```

默认持续运行到 **Ctrl+C**，每 15 秒输出连接状态心跳。无行情时也不会自动关闭。

限时验证：

```bash
.venv/bin/python projects/ctp_demo/demo.py --duration 90
```

指定合约（必须使用当前有效代码）：

```bash
.venv/bin/python projects/ctp_demo/demo.py --symbols 合约代码1,合约代码2
```

## 配置与输出

- 从 `configs/local/simnow.json` 读取配置；本地文件已被 Git 忽略。
- 可公开的空账号样例：[simnow.example.json](../../configs/simnow.example.json)。复制到本地配置目录后填写账号。
- 每次运行创建新的 `reports/local/ctp_<时间>/`，保存脱敏事件 `events.jsonl`、最终 `summary.json` 和 CTP 会话文件。
- `--output` 可指定新的输出目录，已有目录不会覆盖。
- `--duration 0` 表示不限时，其他正数表示运行秒数。限时验证不等于全天稳定性测试。

默认从黄金、白银、铜、螺纹钢四个品种查询正在交易且未到期的期货合约，每品种先观察最近六个到期月份。观察 20 秒后，每品种选择累计成交量最高、收到多条且发生更新的合约，取消其他候选订阅。这是候选范围内的选择，不声称全市场排名第一。没有合格候选时继续观察并再次尝试。

`Tick` 输出包含行情时间、最新价、买一、卖一、累计成交量；无效价格显示 `None`。行情推送不等于自己的成交回报。

## 测试

```bash
.venv/bin/python -m unittest discover -s projects/ctp_demo -p 'test_*.py' -v
```

六项测试使用明确标记的假 API 或纯数据，验证自动查询筛选、持续运行与终止、登录失败、订阅后无行情、异常价格和筛选逻辑；真实连接证据见 [报告](../../reports/第一部分作业报告.md)。

## 环境说明

本机已准备好 `.venv`，可直接运行。Python 3.12.14、vnpy 4.4.0、vnpy_ctp 6.7.7.2；没有配置或启动图形交易界面。原始源码阅读版本与本机兼容运行版本分别记录，见 [Mac 环境笔记](../../wiki/code/mac-environment.md)。

恢复 CTP 源码并在新的 Mac arm64 构建目录编译（需要 Xcode 命令行工具及 `uv`；不要覆盖已有构建目录）：

```bash
.venv/bin/python scripts/fetch_ctp_mac.py
uv venv --python 3.12 .venv-build
uv pip install --python .venv-build/bin/python pybind11==2.13.6 'setuptools>=70' wheel
UV_CACHE_DIR=/tmp/quant-uv-cache .venv-build/bin/python scripts/build_ctp_mac.py
```

以上用于已有 vnpy 运行环境中的 CTP 重建。本地 wheel 的动态库路径指向 `build/vnpy_ctp_mac_6_7_7/`，该目录不能移走或删除。

## 价格触发交易程序

`demo.py` 始终只输出行情；新增 `trade.py` 负责一只合约的交易前检查与单次仿真交易。用户已确认 1 手、10 万元模拟止损阈值、成交后 60 秒自动平仓。

默认检查模式只查询和记录，不发单：

```bash
.venv/bin/python projects/ctp_demo/trade.py
```

显式启用交易时必须提供固定阈值或已实现的阈值固定规则，并设置带时区的有效期；本次参数在本地 `configs/local/trade-plan.json`。**下面的命令可能发送仿真订单**，不是行情查看命令：

```bash
.venv/bin/python projects/ctp_demo/trade.py --plan configs/local/trade-plan.json --execute --duration 180
```

`--duration` 在执行模式中限制等待开仓的时间；已成交仓位继续按 60 秒/止损规则退出。首次实验只支持上期所黄金、白银的 1 手多头，目标合约须无已有持仓和活动委托。

发单前将意图提交到 `data/trade_state/` 的 SQLite 文件；同一账号发现已发单意图时拒绝再次执行。本次已完成开仓和平仓，**不能把上面的命令当作可重复运行的演示**。不要删除账本来重跑，也不要同时用其他程序操作同一账号。断线、报单/撤单超时或无法平仓时进入人工核对，不宣称已平仓。

风控、触发和平仓边界以及最终成交验收统一见[第一部分报告](../../reports/第一部分作业报告.md)。新运行的日志与汇总仍在 `reports/local/trade_<时间>/`；账户资金和原始查询结果仅保留本地。
