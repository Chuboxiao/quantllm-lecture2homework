# 第二讲：老师的演示顺序与本项目范围

来源：[教师整理的提示词](https://github.com/aslan9/pku_quantllm/issues/2#issuecomment-5738097794)、[依赖与账号补充](https://github.com/aslan9/pku_quantllm/issues/2#issuecomment-5738166328)。本地保留[删去演示账号配置的快照](../../raw/web/issue-2-teacher-comments.md)。

| 顺序 | 老师让 Agent 做什么 | 本项目对应位置 |
|---|---|---|
| 1 | 阅读 llm-wiki，初始化学习项目 | AGENTS.md 和 wiki |
| 2 | 下载并消化 vnpy、vnpy_ctp、vnpy_ctastrategy | raw/repos 和三个源码摘要 |
| 3 | 从底层 Python API 实现登录、订阅、持续打印行情 | `projects/ctp_demo/demo.py`，已验收 |
| 4 | 加入 TD API，超过指定价格下单，先看方案 | `projects/ctp_demo/trade.py`，已完成一次开平仓 |
| 5 | 理解底层标准化、中层引擎和策略应用 | [架构概念页](../concepts/architecture.md) |
| 6 | 每轮尝试 10–20 个因子、最多 4 轮 | [因子研究](../../projects/factor_research/README.md)，本项目选均线动量 clue，完成第 1 轮 12 个候选 |

提示词记录演示流程，不是完整评分细则。老师给出“先看方案再执行”的演示提示；实际实施按用户具体需求和已有授权推进，不把同学的做法当成新的课程强制要求。

用户选择先本地完成、自己再上传；已注册 SimNow，不配置完整交易界面。后续真实运行结果分别见 [交易报告](../../reports/第一部分作业报告.md) 和 [因子报告](../../reports/第二部分作业报告.md)。

课堂的“超过价格下单”是阈值触发。源码的 `BarData` 是 K 线；两者含义不同，见[事件与数据](../concepts/events-and-data.md)。

原始课件：本地 `raw/course/第一讲.pdf`、`raw/course/第二讲-VeighNa.pdf`。本轮以教师提示词和实际源码为阅读主线，未重新逐页分析课件。
