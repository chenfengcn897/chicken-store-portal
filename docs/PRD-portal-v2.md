# Portal 页面需求重构 PRD

## 背景
福浔道数据门户 Portal 需要重构部分页面，使展示内容更贴合实际业务需求。

## 项目路径
- Portal: /home/ubuntu/chicken-store-portal/
- 虚拟环境: /home/ubuntu/chicken-store-portal/venv/
- 模板目录: /home/ubuntu/chicken-store-portal/templates/
- DB: docker exec chicken-store-db mysql -uroot -pChickenStore2026! chicken_store
- systemd: chicken-store-portal (端口 5006)
- Nginx: /portal/ -> :5006
- 认证: auth_token cookie = fxd2026 或 session['logged_in']
- app.py 有 ReverseProxied middleware，url_for 自动生成 /portal/ 前缀

## 页面清单（共 8 个）

### 保留不变的页面（4个）
1. /dashboard → 改菜单名为"物料动态"（原"库存仪表板"），页面内容不变
2. /revenue-dashboard → 营收看板，不变
3. /shops-compare → 双店对比，不变
4. /cost-analysis → 成本分析，不变

### 需要重构的页面（4个）

#### 页面 1: / (首页 - 营收概览) → 保留不变
当前已正常工作，保留。

#### 页面 2: /logs (采集日志) → 重构
**需求**: 展示每次数据采集的详细信息

**数据源**: 
- 主表: collect_logs (目前为空，需要改为读取 /home/ubuntu/chicken-store/logs/collect_all.log 文件解析)
- 日志格式示例:
  ```
  [2026-05-30 04:00:01] === 数据采集 开始 ===
  [04:00:01] [MAIN] === 统一数据采集 开始 ===
  [04:00:01] ▶ 食亨订单: 开始采集...
  [04:00:15]   CSV 下载完成: 138 行
  [04:00:15]   解析: 137 条订单
  [04:00:15]   入库: 新增 5 条 (重复跳过 132 条)
  [04:00:16] ▶ 食亨采购: 开始采集...
  [04:00:18]   采集完成: {'new': 2, 'updated': 0, 'skipped': 3}
  [04:00:18] ▶ 配送费: 开始采集...
  [04:00:19]   2026-05-29: 109条记录, 107单有配送费, 合计554.0元, 更新0条
  [04:02:12] [MAIN] === 统一数据采集 完成 (错误数: 0) ===
  [2026-05-30 04:02:12] === 数据采集 结束 (exit=0, 131s) ===
  ```

**展示字段**:
| 字段 | 说明 |
|------|------|
| 采集时间 | 从日志解析，如 2026-05-30 04:00 |
| 采集系统 | 食亨订单 / 食亨采购 / 配送费(外卖邦) |
| 状态 | 成功✅ / 失败❌ / 部分成功⚠️ |
| 采集数量 | 如 "137条订单, 新增5条" |
| 耗时 | 如 "131秒" |
| 完整性 | 是否有错误(错误数: 0 = 完整) |

**补充**: 同时读取 /home/ubuntu/chicken-store/logs/ 下的其他日志文件:
- cron_delivery_fee.log (配送费采集)
- health.log (健康检查)

**排序**: 按时间倒序

#### 页面 3: /orders (订单查询) → 重构
**需求**: 查询两家店全部订单，展示成本和毛利

**数据源**: merged_orders 表 + product_recipes(BOM成本)

**展示字段**:
| 字段 | 说明 | 数据来源 |
|------|------|----------|
| 订单时间 | order_date + order_time | merged_orders |
| 门店 | shop_name | merged_orders |
| 平台 | platform | merged_orders |
| 商品 | products | merged_orders |
| 预计收入 | income | merged_orders |
| 配送费 | delivery_fee (含第三方配送费+小费) | merged_orders |
| 物料成本 | 根据 products 解析出鸡的数量 × ¥34.29/只 | 计算字段 |
| 毛利 | income - delivery_fee - 物料成本 | 计算字段 |

**物料成本计算逻辑**:
- 从 products 字段解析商品名和数量
- 整只鸡(含"整只") = 1只 × ¥34.29
- 半只鸡(含"半只") = 0.5只 × ¥34.29
- 排骨大份 = ¥25 (估算)
- 排骨小份 = ¥15 (估算)
- 乳鸽 = ¥15/只 (估算)
- 其他商品(饮料/酱料/馒头等) 成本忽略不计
- BOM总成本 ¥34.29/只 来自 app.py 的 UNIT_CONVERSION 换算

**筛选**: 门店(下拉)、平台(下拉)、日期范围
**排序**: 默认按 order_date DESC, order_time DESC
**分页**: 每页 50 条

#### 页面 4: /inventory → 改为 /recipes (产品配方)
**需求**: 展示每个产品的配方明细、配方成本、产品售价

**数据源**: product_recipes + materials + UNIT_CONVERSION换算

**展示字段**:
| 字段 | 说明 |
|------|------|
| 产品名称 | product_name |
| 配方明细 | 物料名 × 用量 (展开/折叠) |
| 配方成本 | SUM(物料单价/换算比 × 用量) |
| 产品售价 | 从 merged_orders.products 解析出的价格 |
| 近30天销量 | 从 merged_orders.products 统计 |

**排序**: 按近30天销量降序
**注意**: 
- 物料单价需要用 UNIT_CONVERSION 换算（和 cost-analysis 页面一致）
- UNIT_CONVERSION 字典已在 app.py 顶部定义

## 导航栏变更

base.html 和所有独立HTML页面的导航菜单统一为:
1. 营收概览 → /
2. 订单查询 → /orders  
3. 产品配方 → /recipes (原"库存状态" /inventory)
4. 采集日志 → /logs
5. 物料动态 → /dashboard (原"库存仪表板")
6. 营收看板 → /revenue-dashboard
7. 双店对比 → /shops-compare
8. 成本分析 → /cost-analysis

**重要**: 所有页面的导航栏菜单项文字和顺序必须完全一致。

## 技术约束
- Python 3.10, Flask, pymysql (DictCursor)
- DB: host='127.0.0.1', user='root', password='ChickenStore2026!', db='chicken_store'
- 模板用 Tailwind CSS (CDN)
- 继承 base.html 的页面: revenue.html, orders.html, recipes.html(新), logs.html
- 独立 HTML 的页面: dashboard.html, revenue_dashboard.html, shops_compare.html, cost_analysis.html
- app.py 顶部有 UNIT_CONVERSION 字典，直接引用
- AUTH_TOKEN = 'fxd2026'，login_required 检查 session 或 auth_token cookie 或 ?token= 参数

## 验收标准
1. 所有 8 个页面返回 200，size > 2000
2. 导航栏在所有页面完全一致（文字+顺序+链接）
3. 采集日志页面能展示最近的采集记录
4. 订单页面展示毛利计算
5. 产品配方页面按销量排序
6. 物料动态页面内容不变，仅菜单名改变
7. 完成后 git push
