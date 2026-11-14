# A 股短线情绪分析

基于 [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) 开发的收盘后分析模块，用涨停、炸板、连板接力和市场广度指标描述短线交易状态。我的开源贡献集中在情绪模块的数据接入、指标计算、SQLite 快照、FastAPI 和验证测试。上游项目提供应用框架、配置、数据库和交易日历。

[功能分支](https://github.com/liyvxvan-star/daily_stock_analysis/tree/feat/a-share-sentiment-phase1) · [上游 PR #2525](https://github.com/ZhuLinsen/daily_stock_analysis/pull/2525) · [需求 Issue #1939](https://github.com/ZhuLinsen/daily_stock_analysis/issues/1939)

## 贡献范围

- **生成和保存历史快照。** 按来源及交易日隔离数据，保存数据来源、统计口径版本、质量状态和输入指纹。重复生成相同结果返回 `unchanged`。输入或口径冲突时返回 `409`，保留已有快照。
- **查询和回填。** 提供手动生成、日期列表、单日详情和趋势四个 API。趋势使用目标日之前的 **10、30 或 60 个实际交易日**，明确返回漏采日期和口径不同的日期。东方财富和国泰安支持按交易日区间回填及 `--dry-run`。
- **多数据源与质量校验。** 接入东方财富和本地国泰安导出，并提供 Python 适配器注册接口。当日东方财富快照核对昨日候选股票及其板数，并检查现货分页行数、总数和代码唯一性。数据无法核实时，受影响的指标可留空并标记 `partial`。

工程实现位于 `feat/a-share-sentiment-phase1`。截至 2026-11-14，上游 PR #2525 已提交，仍待合入。

## 指标口径

| 指标 | 计算方式 |
| --- | --- |
| 涨停家数 | 当日收盘封住涨停的股票数量 |
| 炸板率 | 当日触及涨停但收盘未封板的股票数量 ÷ 当日触及涨停的股票数量 |
| 最高连板、连板梯队 | 按连续交易日的收盘涨停统计，分别返回最高板数和各板位家数 |
| 1 进 2 与高阶晋级率 | 对上一交易日首板、二板、三板、四板及以上股票分组，按代码核对当日继续封板的数量，再除以对应昨日组的家数 |
| 跌停覆盖率、上涨股票占比 | 分别用有效行情中的跌停股数、上涨股数除以同一批有效股票数 |
| 成交额及其变化 | 汇总当日有效行情的成交额。与上一交易日同源、同口径的有效快照比较，返回差额和变化比例 |

分母为零时比例返回 `null`。历史记录缺失时按交易日断开连板序列。

| 来源 | 统计范围与运行方式 |
| --- | --- |
| 东方财富 `eastmoney` | 默认来源，统计范围取决于供应商返回的股票池和有效行情。成交额、上涨占比及跌停覆盖率依赖当日有效行情。近期回填取决于历史接口覆盖 |
| 国泰安 `csmar` | 使用本地授权 ZIP，覆盖供应商标记正常交易、成交及涨停价等字段有效的沪深主板股票。支持单工作簿、单工作表导出 |
| 自定义 `custom:<id>` | 服务端注册 Python 适配器后按日生成。由适配器声明股票池并提供每日收盘涨停和盘中触板名单，可计算涨停、炸板、连板和晋级指标 |

[完整字段、历史回填与数据质量规则](https://github.com/liyvxvan-star/daily_stock_analysis/blob/feat/a-share-sentiment-phase1/docs/a-share-sentiment-snapshot.md)

## 本地运行

从功能分支启动。以下命令使用已验证的 Python 3.11，示例服务监听本机。

```bash
git clone --branch feat/a-share-sentiment-phase1 https://github.com/liyvxvan-star/daily_stock_analysis.git
cd daily_stock_analysis
python -m pip install -r requirements.txt
python main.py --serve-only --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs`，在 **Sentiment** 下调用以下端点。日期参数按 `YYYY-MM-DD` 填写。

| 端点 | 用途 |
| --- | --- |
| `POST /api/v1/sentiment/snapshots/{trade_date}/generate` | 手动生成快照，默认使用东方财富 |
| `GET /api/v1/sentiment/snapshots` | 列出已保存的快照 |
| `GET /api/v1/sentiment/snapshots/{trade_date}` | 查看单日指标、来源和质量 |
| `GET /api/v1/sentiment/trend?end_date=2026-10-29&limit=10` | 查询截至目标日前 10 个交易日的趋势及缺失日期 |

用东方财富实测时，选择供应商仍提供数据的已收盘交易日。只读查询读取已保存的 SQLite 快照。配置 `CSMAR_ZIP_PATH` 后，使用 `source=csmar` 选择本地授权数据。只想演示完整流程时，可使用 [自定义来源的合成数据示例](https://github.com/liyvxvan-star/daily_stock_analysis/blob/feat/a-share-sentiment-phase1/docs/a-share-sentiment-snapshot.md#自定义行情适配器)，无需行情账号或授权文件。

## 测试与结果

功能提交 `ae3bd24` 的 Linux 定向回归 **280 项通过**，包括 **47 项情绪专项测试**。测试使用合成行情和临时 SQLite，覆盖交易日缺口、漏行、空池、未来数据隔离、重复执行、冲突和自定义来源。GitHub Actions 的三组后端测试、后端汇总检查和 Docker 构建均已通过。[CI 运行记录](https://github.com/ZhuLinsen/daily_stock_analysis/actions/runs/43571495069)

```bash
python -m pip install -r .github/requirements-ci.txt
python -m pytest -q \
  tests/test_eastmoney_backfill.py tests/test_sentiment_api.py \
  tests/test_sentiment_backfill.py tests/test_sentiment_snapshot.py \
  tests/test_config_registry.py tests/test_config_env_compat.py \
  tests/test_analysis_api_contract.py
```

较早版本曾用 2026-11-11 的东方财富行情跑通生成与查询。同日重复提交返回 `unchanged`。新版分页校验已通过合成回归，真实接口复测遇到连接中断。[真实样例与验证说明](https://github.com/ZhuLinsen/daily_stock_analysis/pull/2525)

## 本地研究

以国泰安沪深主板受限股票池构建 **682 个交易日**的日度研究样本，使用 Spearman 秩相关、区块 Bootstrap 和跨年份对照检验六项指标的关系。用目标日前 60 个交易日的历史分位回放市场状态，并对照历史相似交易日之后第 1、3、5 个交易日的沪深 300 收益分布。

历史分位、状态回放和相似日分析在本地研究版完成。公开功能分支提供规则指标、快照和历史趋势。仓库中的演示和测试使用合成数据。
