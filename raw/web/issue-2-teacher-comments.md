# 第二节：教师评论快照

获取时间：2026-09-23T11:31:31.491057+00:00

来源：https://github.com/aslan9/pku_quantllm/issues/2

范围：账号 vnpy 的三条教师评论；公开演示账号配置已省略，其余正文保留。此文件是明确删节的网页快照，不是未修改的完整 Issue。

## https://github.com/aslan9/pku_quantllm/issues/2#issuecomment-5738097794

评论更新时间：2026-09-19T01:05:14Z

以下是整理后的提示词：

```
[llm-wiki.md](./llm-wiki.md)

我正在准备学习量化交易系统的开发，请阅读llm-wiki.md中的内容，帮我将当前目录初始化为一个WIKI学习项目。
```


```
非常好，接下来请在raw目录中下载VeighNa平台的三个模块，并帮我阅读源码后进行消化：
vnpy
vnpy_ctp
vnpy_ctastrategy

你可以从gitee下载克隆，网络速度比较快
```

```
非常好，接下来我想要开发一个vnpy_ctp的最小DEMO，请阅读以下需求，帮我完成开发：

基于vnpy_ctp
        从底层Python交易API开始
柜台连接登录
        发起网络连接和登录账号
订阅合约行情
        发送行情订阅请求到服务器
打印行情推送
        将推送过来的数据打印输出

你可以使用以下SIMNOW的仿真账号：
[课堂演示账号配置已省略；本项目使用用户个人 SimNow 配置]
```


```
我想要脚本运行后，持续输出打印行情，不要直接关闭。

选择几个成交比较活跃的合约来订阅。
```

```
好极了，继续下一步：

对接交易下单
        引入TD API
实现策略逻辑
        超过价格下单

因为这一步我不是那么确定，你先给出方案，等我阅读确认后再执行。

写的精简清晰一些，不要长篇大论。
```


```
我已经完成了基于vnpy_ctp的极简交易系统开发DEMO，接下来我想要学习VeighNa构建对于交易系统更完整的理解，请基于以下概念帮我展开学习:

底层接口
        数据结构标准化
        业务流程标准化
中层引擎
        事件引擎总线
        OMS数据缓存
        交易指令路由
策略应用
        单标的时序策略
        多标的投组策略
        价差套利类策略
```

```
请帮我开始一轮新的因子挖掘，每轮10-20个因子，最多跑4轮。

具体的挖掘思路是：动量因子，围绕开盘跳空（或者任何跳空类机制）的思路
```



## https://github.com/aslan9/pku_quantllm/issues/2#issuecomment-5738141944

评论更新时间：2026-09-19T01:11:44Z

课件代码下载链接（包括PPT和harness）：

https://drive.weixin.qq.com/s?k=AEEA4QczAAoDMi5zZr

## https://github.com/aslan9/pku_quantllm/issues/2#issuecomment-5738166328

评论更新时间：2026-09-19T01:15:04Z

其他注意事项：

1. 运行vnpy.alpha因子投研挖掘，需要额外安装相关依赖库：pip install vnpy[alpha]
2. 介于昨天发生的ZCode事件，我个人建议大家作业换个Agent，尤其记住不要在自己常用的电脑（有你个人关键数据的）随便安装Agent（哪怕是什么大厂产品）
3. 连接CTP用的SimNow账号，可以在这里注册：https://www.simnow.com.cn/，服务器地址等信息见这里：https://www.simnow.com.cn/product.action
