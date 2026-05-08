# 调用模式：scheduler

本轮为系统定时调用。

## 定位

scheduler 用于盘前、盘中、午休、盘后等自动化运行。

本模式下没有人工指定任务，Agent 需要根据当前市场阶段、账户、持仓、策略、候选和最近日志，自主判断本轮动作。

## 执行要求

1. 判断当前市场阶段。
2. 读取对应 phase prompt：
   - 盘前 → `phases/premarket.md`
   - 盘中 → `phases/intraday.md`
   - 午休 → `phases/intraday.md`
   - 盘后 → `phases/postmarket.md`
3. 优先处理持仓和已有策略。
4. 再考虑候选池和新机会。
5. 当前阶段不适合执行的动作，应记录原因并推迟。
6. 不为产出内容而强行交易。