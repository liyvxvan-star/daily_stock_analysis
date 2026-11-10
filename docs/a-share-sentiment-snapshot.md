# A 股收盘情绪快照（本地国泰安数据源）

此后端能力需要手动调用生成接口。默认 `CSMAR_ZIP_PATH` 为空，项目启动、日常分析和定时任务不会读取国泰安文件；本功能不新增定时任务或 LLM 调用。配置后，程序直接读取本地授权的 `TRD_Dalyr.xlsx` 压缩包，并把按日快照保存在原项目的 `DATABASE_PATH` 数据库中。请勿提交原始 ZIP、生成的数据库或其中的股票名单。

## 可选东方财富数据源

不配置国泰安时，也可手动调用 `POST /api/v1/sentiment/snapshots/2026-10-29/generate?source=eastmoney`，通过项目使用的 AkShare 数据源直接获取东方财富的涨停池、炸板池和昨日涨停池。详情、列表和趋势接口同样使用 `source=eastmoney` 查询；不传 `source` 时保留原来的国泰安行为。两者分别使用 `CN_A_EASTMONEY_POOL` 和 `CN_A_MAIN_NORMAL_LIMITED_CSMAR` 作为保存范围，不会覆盖或混合。

东方财富的统计对象是**供应商实际返回的股票池**，不是已核实覆盖全部 A 股或沪深主板非 ST 股票的统计；其数字不能当作与国泰安口径等价。涨停家数为当日涨停池数量，炸板率为炸板池数除以涨停与炸板池合计，最高连板和 1 进 2 使用连续交易日涨停池的交集计算。程序验证昨日池和前日涨停池一致、当日连板数与历史池一致、两个当日池无交集；必要的历史池缺失、空响应、异常或存在重复时拒绝生成，不能当成零。`complete` 只代表这些内部校验通过，并不证明供应商市场覆盖完整。

请求在用户手动触发时发出，单个池请求最多尝试两次、每次超时 15 秒；东方财富接口仅能提供近期数据，AkShare 的版本还可能限制历史窗口，不能用于保证多年回填。历史结果是事后获取的供应商数据，可能被修订；输入发生变化时快照返回冲突，不自动覆盖。

和其他模型一样，项目现有数据库初始化会创建本功能的空表 `sentiment_snapshots`，即便未配置数据源；不会因此触发文件读取或快照生成。

读取器目前只支持 ZIP 根目录下**一个** `TRD_Dalyr.xlsx`、且工作簿只有一个工作表；允许国泰安的字段说明文件 `TRD_Dalyr[DES][xlsx].txt` 和 PDF 元数据。包含其他数据文件、分卷、额外工作表或未知附件时会明确报错，不会只读取第一卷。多卷文件需要先用可信流程合并并核对完整性，本功能暂不提供合并工具。

## 配置与调用

在个人 `.env` 中设置 `CSMAR_ZIP_PATH` 为压缩包绝对路径；仓库里的 `.env.example` 只保留空值。服务启动后，手动调用：

```text
POST /api/v1/sentiment/snapshots/2026-10-29/generate
GET  /api/v1/sentiment/snapshots/2026-10-29
GET  /api/v1/sentiment/snapshots?end_date=2026-10-29&limit=30
GET  /api/v1/sentiment/trend?end_date=2026-10-29&limit=30
```

生成接口只接收日期；文件路径来自本地配置，不接受请求传入任意服务器路径。启用管理员认证后，这些接口跟随现有 `/api/v1/*` 认证中间件。对外响应只给出指标、分子分母、来源和质量摘要，不返回授权数据的逐股名单；逐股构成仅保存在本地数据库供核验。

以下是合成测试数据生成的响应片段，不代表真实行情：

```json
{
  "action": "inserted",
  "snapshot": {
    "trade_date": "2026-10-28",
    "quality_status": "complete",
    "metrics": {
      "limit_up_count": 2,
      "break_rate": 0.3333333333333333,
      "max_consecutive": 2,
      "promotion_1_to_2": 1.0
    },
    "break_numerator": 1,
    "break_denominator": 3,
    "promotion_numerator": 1,
    "promotion_denominator": 1
  }
}
```

同一 `(market, trade_date)` 再次提交相同输入返回 `unchanged`。如已保存的数据、来源或口径不同，接口返回 `409 snapshot_conflict`，不会自动覆盖；如果只有 Excel 的工作表范围标记发生变化，其他来源信息、截至当日指纹和计算结果完全相同，则保留原快照并返回 `unchanged`。无文件配置返回 `409 source_not_configured`；指定日期无数据、缺少前两交易日、交易日历不可用或源文件格式不合要求返回 `422 source_unavailable`。缺失数据不当作数值零。

## 第一版统计口径

- 股票池：`Markettype` 为 1 或 4，`Trdsta=1`，`Dnshrtrd>0`，`LimitUp` 为有效正数，且状态、最高价、收盘价通过检查。这是按供应商字段筛选的沪深主板受限股票池，不是全 A 股；`Trdsta=1` 的含义以国泰安字段定义为准，并不独立证明已排除所有其他特殊状态。
- `LimitUp` 和 `LimitStatus` 同时为空时，无法仅凭缺失字段确认是否无涨跌幅限制：记录为来源问题，相关指标记为 `null`、质量标记为 `partial`。现有摘要字段 `target_no_price_limit_excluded` 为兼容旧快照而保留，实际是此类待核实记录的数量，不能当作已确认的无涨跌幅限制股票数量。
- 收盘涨停：`LimitStatus=1`；同时检查收盘价与涨停价是否一致。
- 炸板：最高价触及涨停价，收盘未涨停。炸板率的分母为触及涨停价的股票数；分母为零时比例是 `null`。
- 最高连板：按连续市场交易日的收盘涨停计算。中间停牌、个股无记录或未涨停均按本版本口径中断连板；无法据无记录本身判断是否停牌。如果整个交易日缺失，相关连板标记为不确定，不跨缺口连接。
- 1 进 2：昨日涨停且再前一个市场交易日未涨停的股票是昨日首板；其中今日涨停的数量除以昨日首板数。分母为零时比例是 `null`。

读取时只把目标日及之前的行加入计算和 as-of 摘要；指纹由原有九个必要字段、记录顺序和截至目标日的行生成，沿用第一版规则。Excel 中未来日期的行不参与历史计算和该指纹。国泰安导出文件可能把工作表范围错误标为只有 A 列；读取器按实际单元格重置工作表范围。若历史行内容、顺序或口径发生变化，会产生冲突而不是覆盖旧快照。

`complete` 仅表示本地源文件在上述口径下字段、交易日历和内部价格状态检查通过，且最高连板没有被文件起始日期截断；不表示全市场覆盖、源文件完整性已由独立数据源验证，也无法凭现有字段识别所有个股的缺行原因。出现源数据异常时保存 `partial`，受影响的指标为 `null`；分母确实为零时比例也为 `null`，不等同于数据缺失。公开部署前应检查机构的数据授权条款和现有服务的认证配置。

交易日期使用项目现有的 `exchange-calendars` 沪市交易日历核对；依赖不可用、日期超出其支持范围或文件出现非交易日记录时，拒绝生成。不同版本交易日历可能有不同覆盖范围，应保持版本一致并核对相应交易所公告。

## 本地历史批量回填

在个人 `.env` 或进程环境中设置 `CSMAR_ZIP_PATH` 和 `DATABASE_PATH`，从仓库根目录运行：

```bash
python scripts/backfill_sentiment.py --start-date 2026-10-16 --end-date 2026-10-29 --dry-run
python scripts/backfill_sentiment.py --start-date 2026-10-16 --end-date 2026-10-29
```

`--dry-run` 只计算，不初始化或写入数据库。正式运行使用项目现有的 `DatabaseManager` 与 SQLite 路径。程序按沪市交易日历逐日处理；交易日历不可用时停止，数据文件缺少目标交易日时报告 `failed`，缺少中间交易日时显式断开连板并对受影响指标标记 `partial`，不会把缺口两边的涨停接成连续序列。

每个交易日输出一行 JSON，含 `status`（`inserted`、`unchanged`、`partial`、`conflict` 或 `failed`）、`quality_status` 和 `save_action`；`partial` 也可能是新插入或重复未变，具体动作见 `save_action`。末行输出状态及写入动作汇总。出现 `conflict` 或 `failed` 时退出码为 1；配置、日期区间或日历不可用时退出码为 2。已有快照不自动覆盖。

回填故意逐日调用第一版读取器，保留每个目标日的 as-of 数据指纹和来源字段。真实文件单日读取可能需要几十秒，较长区间回填可能耗时数分钟甚至更久；实际速度取决于文件大小和设备。在证明新读取方式与既有快照逐字段等价之前，不改为共享扫描。历史异常仍记录在 `source_issues_through_target`，但只影响其可能改变的当日、晋级率或当前连板，不会让无关的早期异常永久压低后来快照的质量状态。

## 离线测试与回滚

维护者无需国泰安文件；测试在临时目录生成合成工作簿和 SQLite 数据库：

```bash
python -m pytest -q tests/test_sentiment_snapshot.py tests/test_sentiment_backfill.py tests/test_sentiment_api.py
```

停用功能可清空 `CSMAR_ZIP_PATH` 并停止调用上述手动生成接口。回滚相关代码版本不会自动删除现有 `sentiment_snapshots` 表或数据；是否备份和清理数据库由部署方自行决定，勿对现有数据库自动执行删除操作。
