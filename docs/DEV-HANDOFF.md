# DEV-HANDOFF — Portal v2 重构

## 变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| app.py | 修改 | 新增 /recipes 路由，重构 /logs、/orders，删除 /inventory |
| templates/base.html | 修改 | 统一导航栏（8项+退出） |
| templates/recipes.html | 新增 | 产品配方页，按销量排序 |
| templates/logs.html | 重构 | 解析 collect_all.log 展示采集摘要 |
| templates/orders.html | 重构 | 新增物料成本/毛利计算列 |
| templates/dashboard.html | 修改 | 菜单名改为"物料动态"，内容不变 |
| templates/revenue_dashboard.html | 修改 | 统一导航栏 |
| templates/shops_compare.html | 修改 | 统一导航栏 |
| templates/cost_analysis.html | 修改 | 统一导航栏 |

## API 路由

| 路由 | 方法 | 说明 |
|------|------|------|
| / | GET | 营收概览（不变） |
| /orders | GET | 订单查询，含毛利计算，支持门店/平台/日期筛选，分页50条 |
| /recipes | GET | 产品配方，按近30天销量降序 |
| /logs | GET | 采集日志，解析 collect_all.log，按时间倒序 |
| /dashboard | GET | 物料动态（原库存仪表板，内容不变） |
| /revenue-dashboard | GET | 营收看板（不变） |
| /shops-compare | GET | 双店对比（不变） |
| /cost-analysis | GET | 成本分析（不变） |

## 毛利计算规则

- 整只鸡（含"整只"）= ¥34.29/只
- 半只鸡（含"半只"）= ¥17.15/只
- 排骨大份 = ¥25
- 排骨小份 = ¥15
- 乳鸽 = ¥15/只
- 其他（饮料/酱料/馒头等）= ¥0
- 毛利 = 预计收入 - 配送费 - 物料成本

## 日志解析规则

- 数据源：/home/ubuntu/chicken-store/logs/collect_all.log
- 每次采集以 `=== 数据采集 开始 ===` 为起点，`=== 数据采集 结束 ===` 为终点
- 解析字段：采集时间、各子系统状态、采集数量、总耗时、错误数

## 运行方式

```
# 启动
sudo systemctl restart chicken-store-portal

# 验证（需 auth_token=fxd2026 cookie）
curl -b "auth_token=fxd2026" http://localhost:5006/
curl -b "auth_token=fxd2026" http://localhost:5006/orders
curl -b "auth_token=fxd2026" http://localhost:5006/recipes
curl -b "auth_token=fxd2026" http://localhost:5006/logs
curl -b "auth_token=fxd2026" http://localhost:5006/dashboard
curl -b "auth_token=fxd2026" http://localhost:5006/revenue-dashboard
curl -b "auth_token=fxd2026" http://localhost:5006/shops-compare
curl -b "auth_token=fxd2026" http://localhost:5006/cost-analysis
```

## 自测结果

| 页面 | HTTP | Size |
|------|------|------|
| / | 200 | 20321 |
| /orders | 200 | 87543 |
| /recipes | 200 | 120152 |
| /logs | 200 | 10007 |
| /dashboard | 200 | 23104 |
| /revenue-dashboard | 200 | 31299 |
| /shops-compare | 200 | 14953 |
| /cost-analysis | 200 | 49244 |

所有页面 200，size > 2000 ✅
导航栏 8 项在所有页面完全一致 ✅
物料动态菜单名已更新 ✅
毛利计算字段已展示 ✅
产品配方按销量排序 ✅
采集日志解析 collect_all.log ✅

## Git 提交

commit: d63cfca
message: [developer] portal v2 重构：8页面导航体系，/logs采集日志，/orders毛利计算，/recipes产品配方，/dashboard物料动态

注：仓库无 remote 配置，无法执行 git push。
