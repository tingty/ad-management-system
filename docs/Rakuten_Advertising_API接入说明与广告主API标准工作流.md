# Rakuten Advertising API 接入说明与广告主 API 标准工作流

> 适用系统：广告管理系统 / 广告主数据 → 广告主 API → 广告主报表  
> 适用版本：V4.152
> 本文同时承担两个职责：①说明 Rakuten Advertising 佣金数据应如何拉取；②沉淀今后所有广告主 API 模板开发的标准流程。

---

## 一、结论先行

作为 Rakuten Advertising 的流量商（Publisher）合作方，要拉取“我们推广产品的具体佣金报表”，**核心接口不是 Commissioning Lists，也不是 Advanced Reports 的付款历史**，而是：

```http
GET https://api.linksynergy.com/events/1.0/transactions
Authorization: Bearer <access_token>
```

该接口返回逐笔交易/事件流水，包含：

- `etransaction_id`：交易唯一 ID（本系统幂等键）
- `order_id`：广告主订单号
- `advertiser_id`：广告主 MID
- `offer_id`：产生佣金的 Offer
- `sku_number` / `product_name`：推广商品
- `sale_amount`：销售金额
- `commissions`：发布者佣金
- `currency`：币种
- `process_date` / `transaction_date`：处理时间 / 下单时间
- `transaction_type`：realtime / batch
- `is_event`：是否为 Event（非 Sale）

实测该接口返回顶层 JSON 数组，支持 `page` / `limit` 分页；`limit=300` 时第一页 300 条、第二页 34 条，分页有效。

---

## 二、Rakuten 官方文档梳理

### 2.1 Access Token 获取

官方文档：<https://developers.rakutenadvertising.com/guides/access_tokens>

Rakuten 的 API 认证分两层：

1. **token-key**：由 Developer Portal Application 的 `client_id:client_secret` 做 Base64 得到。
2. **access_token**：调用 token endpoint 换取，所有业务 API 都用它。

#### 生成 token-key

```bash
echo -n "{client_id}:{client_secret}" | base64
```

Linux/macOS 得到 87 位左右、以 `=` 结尾的字符串，即 token-key。

#### 换取 access_token

```http
POST https://api.linksynergy.com/token
Authorization: Bearer {token-key}
Content-Type: application/x-www-form-urlencoded

scope={account-id}
```

成功响应：

```json
{
  "access_token": "{bearer-token}",
  "expires_in": 3600,
  "refresh_token": "{refresh-token}",
  "token_type": "bearer"
}
```

要点：

- `access_token` 有效期 3600 秒（1 小时）。
- token endpoint 限流 100 次/分钟。
- 刷新时：

```http
POST https://api.linksynergy.com/token
Authorization: Bearer {token-key}
Content-Type: application/x-www-form-urlencoded

refresh_token={refresh-token}&scope={account-id}
```

- 刷新会让当前 access_token 立即失效。
- Developer Portal 也可手工生成 60 分钟有效的临时 access_token，但**不适合长期自动调度**。

#### V4.152 真实凭据验证补记（不记录任何密钥值）

用一组真实 Application 的 `client_id / client_secret / account-id` 做只读验证，得到与上面文档示例不同的实际行为：

1. 按文档示例用 `Authorization: Bearer {token-key}` + `scope={account-id}` 换 token → `401 invalid_client`。换成 `Basic`、补 `grant_type` 等变体仍为 401。
2. 改用 body 表单 `grant_type=client_credentials&client_id=...&client_secret=...&scope={account-id}` → `HTTP 200`，返回 `access_token / expires_in=3600 / token_type=bearer`（该方式未返回 `refresh_token`，到期重新换取即可）。
3. 用该 token 调 Events API 时若不带 `x-rm-preferred-sid` 头 → `401 missing x-rm-preferred-sid header`；带 `x-rm-preferred-sid: {account-id}` → `HTTP 200`。
4. 因此系统新增 `oauthcc:client_id|client_secret|account_id` 组合凭据格式：**body 换 token + 业务请求自动带 SID 头**；原有直传 token 与 `oauth:token-key|account-id` 行为保持不变。
5. 凭据值不写入代码、文档、数据库或日志；测试滑窗对 `client_id / client_secret / access_token` 全部脱敏。

### 2.2 Web Security Token

Advanced Reports API 的 `token` 查询参数不是 Bearer token，而是 Publisher Dashboard 里的 Web Security Token。

获取路径：

- Publisher Dashboard → Support → Manage Tokens → Security Token
- 或 <https://publisher.rakutenadvertising.com/api-links/tokens>

注意：**调用 `/events/1.0/transactions` 不需要 Web Security Token，只需要 Bearer access_token。**

### 2.3 Events Transactions API（本系统主数据源）

官方 Swagger：<https://developers.rakutenadvertising.com/documentation/en-US/affiliate_apis#/Events/get_events_1_0_transactions>

```http
GET https://api.linksynergy.com/events/1.0/transactions
Authorization: Bearer <access_token>
Accept: application/json
```

主要参数：

| 参数 | 是否必填 | 格式/示例 | 含义 |
|---|---:|---|---|
| `process_date_start` | 否 | `2026-11-19 00:00:00` | 按 Rakuten 处理时间过滤起 |
| `process_date_end` | 否 | `2026-11-26 00:00:00` | 按 Rakuten 处理时间过滤止 |
| `transaction_date_start` | 否 | `2020-05-01 12:00:00` | 按订单发生时间过滤起 |
| `transaction_date_end` | 否 | `2020-05-02 12:00:00` | 按订单发生时间过滤止 |
| `limit` | 否 | 默认 100，实测可 300 | 每页条数 |
| `page` | 否 | 默认 1 | 页码 |
| `currency` | 否 | `USD/CAD/GBP/EUR/BRL/AUD/JPY` | 币种筛选 |
| `type` | 否 | `batch/realtime` | 交易类型筛选 |

实测响应为数组：

```json
[
  {
    "etransaction_id": "CA6C79077E98AB6363074966A33A2363",
    "advertiser_id": 53552,
    "sid": 4752032,
    "order_id": "19248157884806",
    "offer_id": "2103603",
    "sku_number": "TI0000990",
    "sale_amount": -7.15,
    "quantity": 1,
    "commissions": -0.3575,
    "currency": "USD",
    "process_date": "Thu Nov 26 2026 07:02:32 GMT+0000 (UTC)",
    "transaction_date": "Tue Nov 24 2026 20:33:08 GMT+0000 (UTC)",
    "transaction_type": "realtime",
    "product_name": "Worry-Free Purchase",
    "u1": "",
    "is_event": "N",
    "commission_list_id": null,
    "lock_status": "#N/A",
    "order_auto_lock_date": "..."
  }
]
```

字段口径：

- `commissions < 0` 表示退款/冲正，本系统按订单净额归零判定取消单。
- **实测口径：同一个 `etransaction_id` 会各返回一条 `is_event=N` 与 `is_event=Y`，两条的订单、SKU、金额、佣金完全相同；`Y` 是 Event 视角，不能再次计佣。本系统只取 `is_event=N` 作为佣金流水。**
- `lock_status` 实测可为 `#N/A`，不是标准状态枚举。
- 实测字段是 `commission_list_id`（单数），官方文档示例曾写 `commissions_list_id`（复数），**以真实返回为准**。

#### 长期自动拉取边界（V4.151 排查补记）

官方 Events API 指南明确：该接口**不应用于历史数据**，只保存前 1–2 周数据用于 u1 点击匹配；官方也**不建议用它计算 expected commissions**，而应用 Publisher Dashboard 的 Signature Orders Report / Individual Item Report 做佣金预期核算。接口用于跟踪转化表现属于 directional 用途。

**V4.152 实测补充：**

- 上游对 `process_date_start` 有硬性 30 天限制：超过 30 天直接返回 `HTTP 400 RouteRequirements`，提示必须填写距今不超过 30 天的时间，更早数据应改用 Publisher Dashboard 的 Signature Orders Report。因此回填窗口不得超过 30 天，推荐按 7 天滚动。
- 同一份凭据用不同 `x-rm-preferred-sid` 拉到的数据完全不同：本次提供的 `account-id=4572032` 在近 7 天窗口返回 0 条；改用返回值中实际出现的 `sid=4752032` 则拿到 186 条原始记录，其中 `is_event=N` 有效流水 94 条、31 个订单，币种 USD/AUD/CAD。**SID 填错时上游返回 200 空数组而不是报错**，排查空数据时必须先核对响应记录的 `sid` 是否与填写的 account-id 一致（两者极接近，易抄错）。

因此系统采用以下口径：

- 可以长期做到的是**持续增量拉取 + 本地沉淀**：每日/每小时长期滚动拉取最近 1–2 周，按 `etransaction_id` 幂等 upsert，重复扫描窗口内已落库数据不重复计佣。
- 不能把 Events API 当作**多年历史回溯源**：超过 1–2 周后上游可能不再返回，历史完整性以系统本地已落库数据为准。
- 财务/付款对账仍需 Advanced Reports + Web Security Token，或 Publisher Dashboard 报表；广告主报表中的 Events 数据应标注为“投放转化/佣金流水视角”，不替代后台最终结算。
- 凭据层面可以长期自动运行：`token-key` 只要 Application 的 client_id/client_secret 未撤销就可持续换取新 token；access token 仅 1 小时有效。系统每次调度用 `oauth:{token-key}|{account-id}` 自动换 token，不需要人工每天更换。
- token endpoint 与 Events endpoint 均为 100 次/分钟；应避免把所有连接集中在同一分钟、同一窗口反复全量拉取。

### 2.4 Commissioning Lists API（规则清单，不是佣金流水）

官方帮助中心：<https://pubhelp.rakutenadvertising.com/hc/en-us/articles/50298549908109-Commissioning-Lists-API>

```http
GET https://api.linksynergy.com/v1/commissioninglists
GET https://api.linksynergy.com/v1/commissioninglists/{list-ID}
Authorization: Bearer <access_token>
```

参数：`advertiser`、`goid`、`oid`、`last_modified_range`（`1d/7d/30d`）、`limit`（默认 10，最大 200）、`page`。

响应示例结构：

```json
{
  "_metadata": {
    "api_name_version": "commissioninglists-v1.0.0",
    "page": 1,
    "limit": 10,
    "total": 100,
    "_links": { "next": "...", "self": "..." }
  },
  "commissioninglists": [
    {
      "advertiser": { "id": 111, "details": "/v2/advertisers/111" },
      "offers": [{ "goid": 9999999, "oid": 7777777 }],
      "list_name": "Existing",
      "list_id": "64075a09a57a9800056665ggeff",
      "last_modified_datetime": "2025-02-21T23:29:48.216Z",
      "details": "/v1/commissioninglists/64075a09a57a9800056665ggeff"
    }
  ]
}
```

用途：

- 查询广告主动态佣金规则涉及哪些 SKU / 商品名单；
- 结合 Offers API 理解“哪些产品按什么规则计佣”。

注意：**它不返回已产生佣金，不能作为报表流水。**

### 2.5 Advanced Reports API（付款历史，不是商品级佣金）

官方 Swagger：<https://developers.rakutenadvertising.com/documentation/en-US/affiliate_apis#/Advanced%20Reports/get_advancedreports_1_0>

```http
GET https://api.linksynergy.com/advancedreports/1.0?reportid=1&token={web_security_token}&bdate=YYYYMMDD&edate=YYYYMMDD
Authorization: Bearer <access_token>
```

`reportid`：

- `1`：Payment history summary
- `2` / `22`：Advertiser payments history
- `3` / `23`：Payment details

其他参数：`payid`、`invoiceid`、`nid`、`lang`、`locale`。

用途：对账付款批次与发票。它还需要 Web Security Token，且不是按推广商品统计佣金的接口。

---

## 三、推荐拉取顺序

```text
1. Developer Portal 建 Application，拿 client_id / client_secret
2. Base64(client_id:client_secret) 生成 token-key
3. POST /token，scope=account-id，拿 access_token（3600 秒）
4. （可选）GET /v1/offers + /v1/commissioninglists
   → 理解广告主 Offer、动态佣金规则、SKU 名单
5. GET /events/1.0/transactions
   → 按 process_date 分窗、page/limit 翻页，拿逐笔佣金流水
6. 系统按 etransaction_id 幂等写入 api_source_record / api_unified_fact / api_fact_item / api_fact_ext
7. 「广告主报表」读统一事实表与订单最终视图，展示 KPI、明细与下钻
8. （可选）GET /advancedreports/1.0 做付款批次对账
```

---

## 四、本系统实现口径

### 4.1 模板

- 模板 code：`rakuten_advertising`
- 显示名：`Rakuten Advertising`
- 数据源：`Events / transactions`
- 凭据输入支持三种：
  1. 直接填 `access_token`（Developer Portal 手工生成，60 分钟有效，不适合长期调度）；
  2. 填 `oauth:{token-key}|{account-id}`，系统用 Bearer token-key 自动调用 `/token` 换取 access_token；
  3. **（V4.152 推荐）**填 `oauthcc:{client_id}|{client_secret}|{account-id}`，系统用 body `client_credentials` 换 token，并自动给业务请求加 `x-rm-preferred-sid: {account-id}` 头。真实验证中只有方式 3 对该 Application 可用。
- `token-key` 由 `Base64(client_id:client_secret)` 得到；`account-id` 作为 `scope`。当前界面仍是单一凭据输入框，未拆成 `client_id / client_secret / account_id` 三个独立字段，三个值用 `|` 拼接录入；如需三字段录入，应作为后续版本的小改动实现。
- **account-id 必须与该 Application 有权访问的 SID 一致**，填错时 Events API 返回 200 空数组而非报错，需核对响应记录的 `sid` 字段。

### 4.2 协议配置

模板只声明协议能力，业务层零渠道分支：

- `style=rest`、`http_method=GET`、`auth=bearer`
- `endpoint_path=events/1.0/transactions`
- `date_params={since: process_date_start, before: process_date_end}`
- `date_value_format=rakuten_datetime`
- `page_param=page`、`page_size=300`、`complete_when_short=true`
- `record_filter={field: is_event, equals: N}`：过滤 Event 重复视角，避免重复计佣
- `external_id_path=etransaction_id`
- `credential` 声明 token-key 换取规则；`credential.alternates` 声明 `oauthcc:` 的 client_credentials 换取方式与 `request_headers`（SID 头）模板，二者都是协议层通用能力，业务代码无渠道分支

### 4.3 字段映射

| Rakuten 字段 | 统一目标 | 说明 |
|---|---|---|
| `etransaction_id` | `source_record.external_id` / `fact.commission_id` | 幂等键 |
| `order_id` | `fact.order_id` | 订单合并键 |
| `advertiser_id` | `fact.advertiser_name` / `ext.advertiser_id` | 官方不返回名称，先显示 MID |
| `transaction_date` | `fact.event_date` | `rakuten_datetime` 转 UTC |
| `process_date` | `fact.posting_date` | `rakuten_datetime` 转 UTC |
| `transaction_type` | `fact.action_status` / `fact.event_name` | batch / realtime |
| `sale_amount` | `fact.sale_amount_usd` / `item.unit_price_usd` | 原币数值 |
| `commissions` | `fact.commission_amount_usd` / `item.commission_usd` | 原币数值 |
| `sku_number` | `item.sku` | 商品 SKU |
| `quantity` | `item.quantity` | 数量 |
| `currency` | `ext.currency` | 币种 |
| `product_name` | `ext.product_name` | 商品名 |
| `offer_id` / `commission_list_id` | `ext.*` | 规则溯源 |
| `is_event` / `lock_status` / `order_auto_lock_date` | `ext.*` | 原始语义保留 |

### 4.4 币种口径（重要）

Rakuten 实测同一批数据包含 `USD / AUD / CAD`。当前统一事实表金额列历史命名为 `*_usd`，但本模板写入的是**上游原币数值**，并在 `ext.currency` 保留币种。

因此：

- 报表明细和下钻可查看每条流水的真实币种；
- **跨币种 KPI 加总暂不代表统一 USD 金额**；
- 需要精确跨币种汇总时，应先按 `currency` 筛选，或后续接入汇率服务做归一化。

---

## 五、今后新增广告主 API 模板的标准工作流

> 目标：新增渠道 = **文档取证 + 模板配置 + 字段映射 + 真实凭据验收**，不改业务代码、不改报表前端。

### Step 1：官方文档取证（必须先做）

每个新模板都要先记录：

1. 官方文档 URL 与版本；
2. 合作身份：Advertiser / Publisher / Network；
3. 认证方式与凭据字段：Bearer / Basic / Query Token / OAuth；
4. token 有效期、刷新方式、限流；
5. 真正代表“订单级佣金流水”的接口；
6. 请求方法、路径、参数名、日期格式、分页方式；
7. 响应结构示例：records 路径、count 路径、游标、完成标志；
8. 字段清单、币种、时区、状态枚举、取消/退款表达；
9. 哪些接口只是“规则/付款/商品”，不能误当佣金流水。

输出：写入 `docs/` 的接口说明，或追加到本文档。

### Step 2：真实凭据只读验证

- 用真实凭据调用一次最小窗口；
- 只看 HTTP 状态、字段名、样例值，不把 Token 写入代码/日志/数据库；
- 对照文档确认差异（如 Rakuten 的 `commission_list_id` 单复数差异）；
- 401/403 只记为凭据无效，不用 Mock 冒充成功；但下结论前要先把官方文档列出的认证方式都试一遍（Rakuten 本次 Bearer token-key 401、body client_credentials 200）；
- 200 空数组不等于「无数据」：先核对响应中的账号 / SID 字段是否与填写值一致（本次 SID 抄错导致空数组）；
- 记录上游对日期窗口的硬限制（本次 `process_date_start` 不得超过 30 天），回填步长不得越界。

### Step 3：新增模板配置

在 `backend/advertiser_api.py::PRESET_TEMPLATES` 新增一条：

- `code` / `name` / `vendor` / `description`
- `record_object`
- `required_fields`（界面字段完全由文档决定，不套 CJ 三元结构）
- `default_endpoint`
- `protocol`：请求与响应解析的全部差异

禁止在 `advertiser_ingest.py` / `advertiser_scheduler.py` / `advertiser_reports.py` 写 `template_code == ...` 或渠道字段名。

### Step 4：补齐协议层能力（仅通用能力）

若新渠道有新的请求/响应形态，只在 `backend/advertiser_protocol.py` 增加**通用能力**，例如：

- 新的认证方式；
- 新的日期格式；
- 新的分页方式；
- 新的响应包装路径；
- 新的完成标志。

新增能力要有默认值，老模板行为不变。

### Step 5：登记字段映射

在 `backend/migrations.py`：

1. 新增 `XXX_TEMPLATE_ID`；
2. 新增 `XXX_FIELD_MAP_SEED`；
3. 新增版本化迁移函数；
4. 加入 `MIGRATIONS`；
5. 如需新转换类型，在 `advertiser_ingest._convert()` 增加通用 transform。

映射原则：

- 上游全部字段必须登记（可 `__skip__`），原始层永远保留；
- 幂等键、订单键、金额、事件时间必须显式映射；
- 渠道特有字段进 `ext.*`，不轻易改统一表结构；
- 状态枚举同步到 `api_field_label.enum_map_json`。

### Step 6：测试、拉取与调度

复用现有链路：

- 测试连接：`advertiser_api.test_connection()`；
- 手动拉取：`/advertiser-data/connections/{id}/fetch`；
- 历史回填：`/advertiser-data/connections/{id}/backfill`；
- 自动调度：`advertiser_scheduler.run_due()`。

不得新增进程内任务字典；凭据只在内存解密，token 不落库、不回显、不写日志。

### Step 7：报表验收

报表只读统一事实表与订单最终视图，前端表头读 `api_field_label`：

1. 新建连接并测试通过；
2. 手动拉取一条窗口，确认 `api_source_record` / `api_unified_fact` 有数据；
3. 打开「广告主报表」，确认 KPI / 明细 / 下钻能看到该连接；
4. 核对金额、币种、时间与状态口径；
5. 不得为了某个渠道在报表前端硬编码字段名或中文表头。

### Step 8：测试与发版

每个模板版本必须包含：

- 模板字段/协议专项测试；
- 映射落库与报表可见性测试；
- 静态守约测试：业务层无渠道硬编码；
- 干净代码副本 + 隔离 `DATABASE_URL` 全量回归；
- 前端 `tsc --noEmit` 与 `npm run build`；
- 升 `APP_VERSION` → `CHANGELOG.md` → `prepare_release.py --sync` → `--check`；
- commit / tag / push，保留可回滚。

### Step 9：真实数据验收

Mock 测试只证明链路正确，不证明渠道可用。上线前必须：

1. 用真实凭据创建连接；
2. 测试连接返回 200 且有明细；
3. 拉取一个窗口并落库；
4. 人工核对 3–5 条流水与渠道后台一致；
5. 若凭据过期，重新生成或改用自动换取方式。
