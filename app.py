import sys
import os
import re
import math
from datetime import datetime, timedelta, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import pymysql
import pymysql.cursors


# 采购单位 -> 最小使用单位换算比 (来自 purchase_sync_service.py)
UNIT_CONVERSION = {
    "土猪内排": 13,
    "福浔道港式乳鸽": 30,
    "鲜鸡": 1,
    "潮汕金桔油": 2500,
    "甜辣酱": 3000,
    "白醋": 5000,
    "大红浙醋": 2500,
    "白芝麻": 2500,
    "腊八蒜": 5000,
    "花生米": 2500,
    "酸梅酱": 4000,
    "老卤汁": 3000,
    "特制辣椒粉": 500,
    "脆皮王": 1000,
    "脆皮素": 500,
    "烧鸡腌粉（30斤）": 15000,
    "烧鸡腌粉（50斤）": 25000,
    "糯米粉": 2500,
    "胡椒粉": 1000,
    "麦芽糖": 40,
    "食粉": 24,
    "蜂蜜": 24,
    "大纸盒": 500,
    "小纸盒": 500,
    "大手提袋": 500,
    "小手提袋": 500,
    "锡纸盒（大）": 500,
    "锡纸盒（半只装）": 1000,
    "美式吸油纸": 500,
    "1安酱料杯": 1000,
    "2安酱料杯": 1000,
    "3安酱料杯": 1000,
    "300圆碗": 300,
    "750方盒": 300,
    "500ml（方盒）白色": 300,
    "一次性手套（品牌配套）": 10000,
    "防油纸袋（小）": 90,
    "精品筷子": 1120,
    "打印纸80X60": 50,
    "手工红糖馒头": 96,
    "糯米鸡饭": 70,
    "手工肉粽": 100,
    "喜力啤酒": 24,
    "百威啤酒": 24,
    "王老吉": 24,
    "鲜橙多": 24,
    "百事可乐（瓶装）": 24,
}

# ── 配方成本缓存（从 product_recipes + materials 动态计算）──────────────
_recipe_cache = {}


def _normalize_product_name(raw_name):
    """将订单产品名规范化，便于匹配 product_recipes.product_name
    例: '招牌爆汁脆皮烧鸡（半只）只用鲜鸡烤制[酸梅酱+半只切块]' -> '招牌脆皮烧鸡-半只'
    """
    name = raw_name
    # 去掉方括号内容（规格/配料）
    name = re.sub(r'\[.*?\]', '', name)
    # 去掉花括号内容（JSON规格）
    name = re.sub(r'\{.*?\}', '', name)
    # 去掉括号内的价格
    name = re.sub(r'（[\d.]+\*\d+）', '', name)
    name = re.sub(r'\([\d.]+\*\d+\)', '', name)
    # 去掉"只用鲜鸡烤制"等描述性后缀
    name = re.sub(r'只用鲜鸡烤制.*', '', name)
    name = re.sub(r'[🔥🌶️]+', '', name)  # 去掉 emoji
    name = name.strip()

    # 关键词映射表：订单名关键词 -> product_recipes 精确名
    KEYWORD_MAP = [
        (['招牌', '烧鸡', '整只'], '招牌脆皮烧鸡-整只'),
        (['招牌', '烧鸡', '半只'], '招牌脆皮烧鸡-半只'),
        (['招牌', '烧鸡', '一只'], '招牌脆皮烧鸡-整只'),
        (['芝麻', '烧鸡', '整只'], '脆皮芝麻烧鸡-整只'),
        (['芝麻', '烧鸡', '半只'], '脆皮芝麻烧鸡-半只'),
        (['烧排骨', '大份'], '烧排骨-大份'),
        (['烧排骨', '小份'], '烧排骨-小份'),
        (['猪肋排', '小份'], '烧排骨-小份'),
        (['猪肋排', '大份'], '烧排骨-大份'),
        (['乳鸽'], '福浔道港式乳鸽'),
        (['糯米鸡饭'], '糯米鸡饭'),
        (['鸡爪'], '鸡爪（盒）'),
        (['红糖馒头'], '手工红糖馒头'),
        (['肉粽'], '手工肉粽'),
        (['可口可乐'], '百事可乐（瓶装）'),
        (['百威'], '百威啤酒'),
        (['喜力'], '喜力啤酒'),
        (['王老吉'], '王老吉'),
        (['鲜橙多'], '鲜橙多'),
        (['金桔柠檬'], '统一金桔柠檬'),
        (['闽超套餐'], '闽超套餐'),
        (['双拼'], '招牌脆皮烧鸡-整只'),
        (['百事可乐'], '百事可乐（瓶装）'),
        (['可乐'], '百事可乐（瓶装）'),
        (['雪碧'], '百事可乐（瓶装）'),
        (['生菜'], '生菜'),
        (['小青柠檬'], '小青柠檬'),
        (['米饭'], '米饭'),
        (['餐盒'], '餐盒'),
        (['常温'], '常温'),
        (['冰'], '冰'),
        (['酸梅酱'], '酸梅酱'),
        (['金桔油'], '潮汕金桔油'),
        (['辣椒粉'], '辣椒粉'),
        (['甜辣酱'], '甜辣酱'),
        (['腊八蒜'], '腊八蒜'),
        (['花生米'], '花生米'),
        (['胡椒粉'], '胡椒粉'),
    ]
    for keywords, mapped in KEYWORD_MAP:
        if all(kw in name for kw in keywords):
            return mapped
    return name


def _calc_recipe_total(rows):
    """计算配方行的总成本"""
    total = 0.0
    for r in rows:
        mat_name = r["material_name"] or ""
        raw_price = float(r["unit_price"] or 0)
        qty = float(r["quantity"] or 0)
        conv = UNIT_CONVERSION.get(mat_name, 1)
        unit_price = raw_price / conv if conv > 0 else raw_price
        total += unit_price * qty
    return total


def get_recipe_cost(product_name):
    """根据产品名称从 product_recipes + materials 计算配方成本，使用缓存避免重复查询。
    当 BOM 数据不完整（合计成本低于合理阈值）时，回退到兜底成本常量。"""
    if product_name in _recipe_cache:
        return _recipe_cache[product_name]

    # 兜底成本常量（BOM 数据不完整时使用）
    FALLBACK_COSTS = {
        '招牌脆皮烧鸡-整只':   34.29,
        '招牌脆皮烧鸡-半只':   17.15,
        '脆皮芝麻烧鸡-整只':   34.29,
        '脆皮芝麻烧鸡-半只':   17.15,
        '烧排骨-大份':         25.0,
        '烧排骨-小份':         15.0,
        '福浔道港式乳鸽':      15.0,
    }
    # 各产品合理成本下限（低于此值视为 BOM 不完整）
    MIN_COST_THRESHOLD = {
        '招牌脆皮烧鸡-整只':   20.0,
        '招牌脆皮烧鸡-半只':   10.0,
        '脆皮芝麻烧鸡-整只':   20.0,
        '脆皮芝麻烧鸡-半只':   10.0,
        '烧排骨-大份':         10.0,
        '烧排骨-小份':          5.0,
        '福浔道港式乳鸽':       8.0,
    }

    # 先规范化名称
    normalized = _normalize_product_name(product_name)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # 1. 精确匹配规范化后的名称
            cur.execute("""
                SELECT r.material_name, r.quantity, r.unit, m.unit_price
                FROM product_recipes r
                LEFT JOIN materials m ON r.material_id = m.id
                WHERE r.product_name = %s
                ORDER BY r.sort_order
            """, (normalized,))
            rows = cur.fetchall()

            # 2. 如果规范化名称没匹配，尝试原始名称精确匹配
            if not rows and normalized != product_name:
                cur.execute("""
                    SELECT r.material_name, r.quantity, r.unit, m.unit_price
                    FROM product_recipes r
                    LEFT JOIN materials m ON r.material_id = m.id
                    WHERE r.product_name = %s
                    ORDER BY r.sort_order
                """, (product_name,))
                rows = cur.fetchall()

            # 3. 最后降级：模糊匹配（取前6字）
            if not rows and len(normalized) >= 4:
                cur.execute("""
                    SELECT r.material_name, r.quantity, r.unit, m.unit_price
                    FROM product_recipes r
                    LEFT JOIN materials m ON r.material_id = m.id
                    WHERE r.product_name LIKE %s
                    ORDER BY r.sort_order
                """, (f"%{normalized[:6]}%",))
                rows = cur.fetchall()

            total = _calc_recipe_total(rows)

            # 4. 若 BOM 合计低于合理阈值，使用兜底常量
            threshold = MIN_COST_THRESHOLD.get(normalized, 0)
            if total < threshold and normalized in FALLBACK_COSTS:
                total = FALLBACK_COSTS[normalized]

            _recipe_cache[product_name] = total
            return total
    finally:
        conn.close()


AUTH_TOKEN = 'fxd2026'

app = Flask(__name__)
app.secret_key = 'chicken-store-portal-secret-key-2026'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_PATH'] = '/'

class ReverseProxied:
    def __init__(self, app, script_name):
        self.app = app
        self.script_name = script_name

    def __call__(self, environ, start_response):
        environ['SCRIPT_NAME'] = self.script_name
        path_info = environ.get('PATH_INFO', '')
        if path_info.startswith(self.script_name):
            environ['PATH_INFO'] = path_info[len(self.script_name):]
        return self.app(environ, start_response)

app.wsgi_app = ReverseProxied(app.wsgi_app, '/portal')


DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': 'ChickenStore2026!',
    'db': 'chicken_store',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}


def get_db():
    return pymysql.connect(**DB_CONFIG)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == 'chicken2026':
            session['logged_in'] = True
            from flask import make_response
            html = '''<!DOCTYPE html><html><head></head><body>
<p>登录成功，正在跳转...</p>
<script>
document.cookie="auth_token=fxd2026;path=/;max-age=86400;SameSite=Lax";
window.location.href="/portal/";
</script>
</body></html>'''
            resp = make_response(html)
            resp.set_cookie('auth_token', AUTH_TOKEN, max_age=86400, path='/', httponly=False, samesite='Lax')
            return resp
        return render_template('login.html', error='密码错误')
    return render_template('login.html', error=None)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def revenue():
    days = request.args.get('days', 7, type=int)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date, shop_name, expected_income, payment_amount, valid_num, average_income "
                "FROM daily_revenues WHERE date >= DATE_SUB(CURDATE(), INTERVAL %s DAY) "
                "ORDER BY date DESC, shop_name", (days,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return render_template('revenue.html', rows=rows, days=days)


@app.route('/api/revenue-chart')
@login_required
def revenue_chart():
    days = request.args.get('days', 7, type=int)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date, shop_name, expected_income FROM daily_revenues "
                "WHERE date >= DATE_SUB(CURDATE(), INTERVAL %s DAY) ORDER BY date, shop_name",
                (days,))
            rows = cur.fetchall()
    finally:
        conn.close()

    from collections import OrderedDict
    dates_set = OrderedDict()
    shops = {}
    for r in rows:
        d = r['date'].strftime('%m/%d') if isinstance(r['date'], date) else str(r['date'])
        dates_set[d] = True
        sn = r['shop_name']
        if sn not in shops:
            shops[sn] = {}
        shops[sn][d] = float(r['expected_income'] or 0)

    labels = list(dates_set.keys())
    datasets = []
    for sn, data in shops.items():
        datasets.append({'shop_name': sn, 'data': [data.get(d, 0) for d in labels]})
    return jsonify({'labels': labels, 'datasets': datasets})


# ── /recipes (产品配方) ──────────────────────────────────────────────────────

@app.route('/recipes')
@login_required
def recipes():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # 近30天各产品销量（从 merged_orders.products 解析）
            cur.execute(
                "SELECT products FROM merged_orders "
                "WHERE order_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) "
                "AND products IS NOT NULL AND products != ''")
            order_rows = cur.fetchall()

            # 统计产品销量
            sales_count = {}
            price_map = {}
            for row in order_rows:
                products_str = row['products'] or ''
                # 格式: "产品名×数量 ¥价格, ..." 或 "产品名 x数量"
                for item in products_str.split(','):
                    item = item.strip()
                    if not item:
                        continue
                    # 提取价格
                    price_match = re.search(r'¥([\d.]+)', item)
                    price = float(price_match.group(1)) if price_match else None
                    # 提取数量
                    qty_match = re.search(r'[×x*](\d+)', item)
                    qty = int(qty_match.group(1)) if qty_match else 1
                    # 提取产品名（去掉数量和价格部分）
                    name = re.sub(r'[×x*]\d+.*', '', item).strip()
                    name = re.sub(r'¥[\d.]+', '', name).strip()
                    if name:
                        sales_count[name] = sales_count.get(name, 0) + qty
                        if price and name not in price_map:
                            price_map[name] = price

            # 获取所有产品配方
            cur.execute(
                "SELECT DISTINCT product_code, product_name FROM product_recipes ORDER BY product_name")
            products = cur.fetchall()

            recipe_list = []
            for prod in products:
                pcode = prod['product_code']
                pname = prod['product_name']

                # 获取该产品的配方明细
                cur.execute(
                    "SELECT r.material_name, r.quantity, r.unit, m.unit_price "
                    "FROM product_recipes r "
                    "LEFT JOIN materials m ON r.material_id = m.id "
                    "WHERE r.product_code = %s ORDER BY r.sort_order", (pcode,))
                ingredients = cur.fetchall()

                # 计算配方成本
                recipe_cost = 0.0
                ingredient_list = []
                for ing in ingredients:
                    mat_name = ing['material_name'] or ''
                    qty = float(ing['quantity'] or 0)
                    raw_price = float(ing['unit_price'] or 0)
                    conv = UNIT_CONVERSION.get(mat_name, 1)
                    unit_price = raw_price / conv if conv > 0 else raw_price
                    cost = unit_price * qty
                    recipe_cost += cost
                    ingredient_list.append({
                        'name': mat_name,
                        'qty': qty,
                        'unit': ing['unit'] or '',
                        'cost': cost,
                    })

                # 匹配销量（模糊匹配产品名）
                sales = 0
                matched_price = None
                for sname, cnt in sales_count.items():
                    if pname in sname or sname in pname:
                        sales += cnt
                        if not matched_price and sname in price_map:
                            matched_price = price_map[sname]

                recipe_list.append({
                    'product_code': pcode,
                    'product_name': pname,
                    'ingredients': ingredient_list,
                    'recipe_cost': recipe_cost,
                    'sale_price': matched_price,
                    'sales_30d': sales,
                })

            # 按近30天销量降序排序
            recipe_list.sort(key=lambda x: x['sales_30d'], reverse=True)

    finally:
        conn.close()
    return render_template('recipes.html', recipes=recipe_list)


# ── /orders (订单查询 + 毛利计算) ────────────────────────────────────────────

# 物料成本计算：从 products 字段解析商品名和数量


def calc_material_cost(products_str):
    """从 products 字段解析物料成本（动态从 product_recipes 计算）"""
    if not products_str:
        return 0.0
    cost = 0.0
    # 提取商品名（价格×数量）匹配，避免 JSON 里的逗号干扰
    import re as _re
    # 匹配模式: 任意字符后跟（价格×数量），用正则定位每个商品
    items = _re.findall(r'[^（]+（[^）]*?）', products_str)
    if not items:
        items = [products_str]
    for item in items:
        item = item.strip().strip(',').strip()
        if not item:
            continue
        # 提取数量
        qty_match = _re.search(r'[×x*](\d+）?)', item)
        qty = int(qty_match.group(1).rstrip('）')) if qty_match else 1
        # 去掉括号及价格数量，只保留产品名
        name = _re.sub(r'（[\d.]+[×x*]\d+）', '', item).strip()
        name = _re.sub(r'¥[\d.]+', '', name).strip()
        # 去除尾部多余的字符（逗号、JSON残片等）
        name = _re.sub(r'[,\[\]{].*', '', name).strip()
        # 使用动态配方成本
        recipe_cost = get_recipe_cost(name)
        cost += recipe_cost * qty
    return cost


@app.route('/orders')
@login_required
def orders():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    shop = request.args.get('shop', '')
    platform = request.args.get('platform', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    where = []
    params = []
    if shop:
        where.append("shop_name = %s")
        params.append(shop)
    if platform:
        where.append("platform = %s")
        params.append(platform)
    if date_from:
        where.append("order_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("order_date <= %s")
        params.append(date_to)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM merged_orders" + where_sql, params)
            total = cur.fetchone()['cnt']
            total_pages = max(1, math.ceil(total / per_page))
            offset = (page - 1) * per_page
            cur.execute(
                "SELECT order_no, shop_name, platform, order_date, order_time, "
                "income, delivery_fee, products FROM merged_orders" + where_sql +
                " ORDER BY order_date DESC, order_time DESC LIMIT %s OFFSET %s",
                params + [per_page, offset])
            raw_rows = cur.fetchall()

            # 获取门店和平台列表（用于下拉筛选）
            cur.execute("SELECT DISTINCT shop_name FROM merged_orders ORDER BY shop_name")
            shops_list = [r['shop_name'] for r in cur.fetchall() if r['shop_name']]
            cur.execute("SELECT DISTINCT platform FROM merged_orders ORDER BY platform")
            platforms_list = [r['platform'] for r in cur.fetchall() if r['platform']]
    finally:
        conn.close()

    # 计算毛利
    rows = []
    for r in raw_rows:
        income = float(r['income'] or 0)
        delivery = float(r['delivery_fee'] or 0)
        mat_cost = calc_material_cost(r['products'] or '')
        gross = income - delivery - mat_cost
        rows.append({
            'order_no': r['order_no'] or '',
            'shop_name': r['shop_name'] or '',
            'platform': r['platform'] or '',
            'order_date': r['order_date'],
            'order_time': r['order_time'],
            'income': income,
            'delivery_fee': delivery,
            'mat_cost': mat_cost,
            'gross': gross,
            'products': r['products'] or '',
        })

    return render_template('orders.html', rows=rows, page=page, total_pages=total_pages,
                           total=total, shop=shop, platform=platform,
                           date_from=date_from, date_to=date_to,
                           shops_list=shops_list, platforms_list=platforms_list)


# ── /logs (采集日志 - 解析日志文件) ─────────────────────────────────────────

LOG_DIR = '/home/ubuntu/chicken-store/logs'
COLLECT_LOG = os.path.join(LOG_DIR, 'collect_all.log')


def parse_collect_log():
    """解析 collect_all.log，返回每次采集的摘要列表"""
    sessions = []
    if not os.path.exists(COLLECT_LOG):
        return sessions

    try:
        with open(COLLECT_LOG, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        return sessions

    # 按采集会话分割（以 "=== 数据采集 开始 ===" 为起始标记）
    session_blocks = re.split(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] === 数据采集 开始 ===', content)

    i = 1
    while i + 1 < len(session_blocks):
        start_time_str = session_blocks[i].strip()
        block = session_blocks[i + 1]
        i += 2

        try:
            start_dt = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
        except Exception:
            continue

        # 解析结束时间和耗时
        end_match = re.search(r'=== 数据采集 结束 \(exit=(\d+), (\d+)s\)', block)
        duration = int(end_match.group(2)) if end_match else None
        exit_code = int(end_match.group(1)) if end_match else None

        # 解析错误数
        err_match = re.search(r'统一数据采集 完成 \(错误数: (\d+)\)', block)
        error_count = int(err_match.group(1)) if err_match else None

        # 解析各子系统
        subsystems = []

        # 食亨订单
        sh_new_match = re.search(r'\[食亨订单\] 采集完成，共新增(\d+)条', block)
        sh_csv_match = re.search(r'CSV 下载完成: (\d+) 行', block)
        sh_parse_match = re.search(r'解析: (\d+) 条订单', block)
        if sh_new_match or sh_csv_match:
            new_cnt = int(sh_new_match.group(1)) if sh_new_match else 0
            csv_cnt = int(sh_csv_match.group(1)) if sh_csv_match else 0
            parse_cnt = int(sh_parse_match.group(1)) if sh_parse_match else 0
            subsystems.append({
                'name': '食亨订单',
                'detail': f'解析{parse_cnt}条, 新增{new_cnt}条',
                'status': 'ok',
            })

        # 食亨采购
        pur_match = re.search(r'\[食亨采购\] 采集完成: \{.*?\'new\': (\d+).*?\'errors\': (\d+)', block)
        if pur_match:
            pur_new = int(pur_match.group(1))
            pur_err = int(pur_match.group(2))
            subsystems.append({
                'name': '食亨采购',
                'detail': f'新增{pur_new}条',
                'status': 'error' if pur_err > 0 else 'ok',
            })

        # 配送费
        fee_match = re.search(r'\[配送费\] 采集完成，共更新(\d+)条', block)
        fee_records = re.findall(r'(\d{4}-\d{2}-\d{2}): (\d+)条记录, (\d+)单有配送费, 合计([\d.]+)元', block)
        if fee_match or fee_records:
            total_fee = sum(float(m[3]) for m in fee_records)
            fee_updated = int(fee_match.group(1)) if fee_match else 0
            subsystems.append({
                'name': '配送费',
                'detail': f'合计¥{total_fee:.0f}, 更新{fee_updated}条',
                'status': 'ok',
            })

        # 对账补采
        recon_match = re.search(r'\[对账补采\] 补采完成: 订单新增(\d+)条, 配送费更新(\d+)条', block)
        if recon_match:
            subsystems.append({
                'name': '对账补采',
                'detail': f'订单新增{recon_match.group(1)}条, 配送费更新{recon_match.group(2)}条',
                'status': 'ok',
            })

        # 整体状态
        if exit_code is not None and exit_code != 0:
            overall_status = 'error'
        elif error_count is not None and error_count > 0:
            overall_status = 'partial'
        else:
            overall_status = 'ok'

        sessions.append({
            'start_time': start_dt,
            'duration': duration,
            'error_count': error_count,
            'status': overall_status,
            'subsystems': subsystems,
        })

    # 按时间倒序
    sessions.sort(key=lambda x: x['start_time'], reverse=True)
    return sessions[:50]


@app.route('/logs')
@login_required
def logs():
    sessions = parse_collect_log()
    return render_template('logs.html', sessions=sessions)


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Core materials: 鲜鸡, 土猪内排, 福浔道港式乳鸽, 鸡爪
            core_names = [
                ('鲜鸡', '%鲜鸡%'),
                ('土猪内排', '%内排%'),
                ('乳鸽', '%乳鸽%'),
                ('鸡爪', '%鸡爪%'),
            ]
            core_cards = []
            alerts = []
            for display, pattern in core_names:
                cur.execute(
                    "SELECT m.name, m.unit, MAX(m.min_stock) as min_stock, "
                    "COALESCE(SUM(CASE WHEN ib.shop_id=1 THEN ib.balance END), 0) as wu, "
                    "COALESCE(SUM(CASE WHEN ib.shop_id=2 THEN ib.balance END), 0) as hu "
                    "FROM materials m "
                    "LEFT JOIN inventory_balance ib ON ib.material_id=m.id "
                    "WHERE m.name LIKE %s GROUP BY m.name, m.unit", (pattern,))
                row = cur.fetchone()
                if row:
                    total = float(row['wu'] or 0) + float(row['hu'] or 0)
                    safety = float(row['min_stock'] or 0)
                    deficit = max(0, safety - total)
                    card = {
                        'display': row['name'],
                        'unit': row['unit'] or '',
                        'store_wu': float(row['wu'] or 0),
                        'store_hu': float(row['hu'] or 0),
                        'total_stock': total,
                        'safety': safety,
                        'deficit': deficit,
                        'in_transit': 0,
                        'status': 'danger' if deficit > 0 else 'ok',
                    }
                    core_cards.append(card)
                    if deficit > 0:
                        alerts.append({
                            'name': row['name'],
                            'stock': total,
                            'safety': safety,
                            'deficit': deficit,
                            'in_transit': 0,
                        })

            # Dynamic rows - last 3 days consumption from inventory_ledger
            today = date.today()
            date_labels = [(today - timedelta(days=i)).strftime('%m/%d') for i in range(2, -1, -1)]
            dynamic_rows = []
            for display, pattern in core_names:
                cur.execute("SELECT id, name FROM materials WHERE name LIKE %s LIMIT 1", (pattern,))
                mat = cur.fetchone()
                if mat:
                    days_data = []
                    for i in range(2, -1, -1):
                        d = today - timedelta(days=i)
                        cur.execute(
                            "SELECT type, SUM(ABS(quantity)) as qty FROM inventory_ledger "
                            "WHERE material_id=%s AND date=%s GROUP BY type",
                            (mat['id'], d))
                        entries = []
                        for le in cur.fetchall():
                            t = le['type']
                            q = float(le['qty'] or 0)
                            if t == 'SALE':
                                entries.append({'label': f'销{q:.0f}', 'color': 'red'})
                            elif t == 'PURCHASE':
                                entries.append({'label': f'进{q:.0f}', 'color': 'green'})
                            elif t == 'STOCKTAKE':
                                entries.append({'label': f'盘{q:.0f}', 'color': 'blue'})
                            else:
                                entries.append({'label': f'{t}{q:.0f}', 'color': 'gray'})
                        days_data.append(entries)
                    dynamic_rows.append({'name': mat['name'], 'days': days_data})

    finally:
        conn.close()

    return render_template('dashboard.html',
                           core_cards=core_cards,
                           alerts=alerts,
                           date_labels=date_labels,
                           dynamic_rows=dynamic_rows,
                           now=datetime.now())


@app.route('/revenue-dashboard')
@login_required
def revenue_dashboard():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date, shop_id, shop_name, expected_income, payment_amount, valid_num, average_income "
                "FROM daily_revenues WHERE date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) "
                "ORDER BY date")
            rev_rows = cur.fetchall()
            cur.execute("SELECT MAX(date) as latest FROM daily_revenues")
            latest_row = cur.fetchone()
            latest = latest_row['latest'] if latest_row and latest_row['latest'] else date.today()
            from collections import OrderedDict
            all_dates = OrderedDict()
            shop_data = {1: {}, 2: {}}
            for r in rev_rows:
                d = r['date']
                d_str = d.strftime('%m/%d') if isinstance(d, date) else str(d)
                all_dates[d_str] = d
                sid = r['shop_id']
                if sid in shop_data:
                    shop_data[sid][d_str] = {
                        'income': float(r['expected_income'] or 0),
                        'orders': int(r['valid_num'] or 0),
                        'aov': float(r['average_income'] or 0),
                    }
            date_labels = list(all_dates.keys())
            trend_datasets = [
                {'label': '五四北店', 'data': [shop_data[1].get(d, {}).get('income', 0) for d in date_labels], 'color': '#FF4D4F'},
                {'label': '湖前店', 'data': [shop_data[2].get(d, {}).get('income', 0) for d in date_labels], 'color': '#52C41A'},
            ]
            aov_datasets = [
                {'label': '五四北店', 'data': [shop_data[1].get(d, {}).get('aov', 0) for d in date_labels], 'color': '#FF4D4F'},
                {'label': '湖前店', 'data': [shop_data[2].get(d, {}).get('aov', 0) for d in date_labels], 'color': '#52C41A'},
            ]
            today = date.today()
            this_end = today
            this_start = today - timedelta(days=6)
            last_end = this_start - timedelta(days=1)
            last_start = last_end - timedelta(days=6)
            wow_period = {
                'this_from': this_start.strftime('%m/%d'),
                'this_to': this_end.strftime('%m/%d'),
                'last_from': last_start.strftime('%m/%d'),
                'last_to': last_end.strftime('%m/%d'),
            }
            cur.execute(
                "SELECT platform, COUNT(*) as cnt, SUM(income) as inc FROM merged_orders "
                "WHERE order_date BETWEEN %s AND %s GROUP BY platform",
                (this_start, this_end))
            this_week = {r['platform']: r for r in cur.fetchall()}
            cur.execute(
                "SELECT platform, COUNT(*) as cnt, SUM(income) as inc FROM merged_orders "
                "WHERE order_date BETWEEN %s AND %s GROUP BY platform",
                (last_start, last_end))
            last_week = {r['platform']: r for r in cur.fetchall()}
            all_platforms = set(list(this_week.keys()) + list(last_week.keys()))
            wow_cards = []
            total_this_orders = total_last_orders = 0
            total_this_income = total_last_income = 0.0
            for p in sorted(all_platforms):
                tw = this_week.get(p, {})
                lw = last_week.get(p, {})
                to = int(tw.get('cnt', 0) or 0)
                lo = int(lw.get('cnt', 0) or 0)
                ti = float(tw.get('inc', 0) or 0)
                li = float(lw.get('inc', 0) or 0)
                total_this_orders += to; total_last_orders += lo
                total_this_income += ti; total_last_income += li
                pct = ((ti - li) / li * 100) if li > 0 else None
                wow_cards.append({'name': p or '未知', 'this_orders': to, 'last_orders': lo,
                    'this_income': ti, 'last_income': li, 'delta': ti - li,
                    'pct': round(pct, 1) if pct is not None else None, 'up': ti >= li})
            total_pct = ((total_this_income - total_last_income) / total_last_income * 100) if total_last_income > 0 else None
            wow_total = {'name': '合计', 'this_orders': total_this_orders, 'last_orders': total_last_orders,
                'this_income': total_this_income, 'last_income': total_last_income,
                'delta': total_this_income - total_last_income,
                'pct': round(total_pct, 1) if total_pct is not None else None,
                'up': total_this_income >= total_last_income}
            cur.execute(
                "SELECT platform, COUNT(*) as orders, COALESCE(SUM(income),0) as income "
                "FROM merged_orders WHERE order_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) "
                "GROUP BY platform ORDER BY orders DESC")
            plat_rows = cur.fetchall()
            colors = ['#FF4D4F', '#FF7A45', '#FFA940', '#52C41A', '#13C2C2', '#1890FF', '#722ED1', '#EB2F96']
            platform_data = {
                'total': sum(int(r['orders'] or 0) for r in plat_rows),
                'labels': [r['platform'] or '未知' for r in plat_rows],
                'values': [int(r['orders'] or 0) for r in plat_rows],
                'colors': colors[:len(plat_rows)],
            }
            weekday_map = ['一', '二', '三', '四', '五', '六', '日']
            cmp7_table = []
            for i in range(6, -1, -1):
                d = today - timedelta(days=i)
                d_str = d.strftime('%m/%d')
                wd = weekday_map[d.weekday()]
                shops = {}
                for sid in [1, 2]:
                    cur.execute(
                        "SELECT expected_income, valid_num, average_income FROM daily_revenues "
                        "WHERE date=%s AND shop_id=%s", (d, sid))
                    row = cur.fetchone()
                    if row:
                        shops[sid] = {'income': float(row['expected_income'] or 0),
                            'orders': int(row['valid_num'] or 0), 'aov': float(row['average_income'] or 0)}
                    else:
                        shops[sid] = {'income': 0, 'orders': 0, 'aov': 0}
                cmp7_table.append({'date': d_str, 'weekday': wd, 'shops': shops,
                    'total_income': shops[1]['income'] + shops[2]['income']})
    finally:
        conn.close()
    return render_template('revenue_dashboard.html', latest=latest, date_labels=date_labels,
        trend_datasets=trend_datasets, aov_datasets=aov_datasets, wow_cards=wow_cards,
        wow_total=wow_total, wow_period=wow_period, platform_data=platform_data,
        cmp7_table=cmp7_table, now=datetime.now())


@app.route('/shops-compare')
@login_required
def shops_compare():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            today = date.today()
            cur.execute(
                "SELECT date, shop_id, expected_income, valid_num FROM daily_revenues "
                "WHERE date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) ORDER BY date")
            rev_rows = cur.fetchall()
            from collections import OrderedDict
            all_dates = OrderedDict()
            s1_data = {}; s2_data = {}
            s1_total_income = s2_total_income = 0.0
            s1_total_orders = s2_total_orders = 0
            for r in rev_rows:
                d_str = r['date'].strftime('%m/%d') if isinstance(r['date'], date) else str(r['date'])
                all_dates[d_str] = True
                inc = float(r['expected_income'] or 0)
                ords = int(r['valid_num'] or 0)
                if r['shop_id'] == 1:
                    s1_data[d_str] = inc; s1_total_income += inc; s1_total_orders += ords
                elif r['shop_id'] == 2:
                    s2_data[d_str] = inc; s2_total_income += inc; s2_total_orders += ords
            date_labels = list(all_dates.keys())
            shop1_income = [s1_data.get(d, 0) for d in date_labels]
            shop2_income = [s2_data.get(d, 0) for d in date_labels]
            cur.execute(
                "SELECT platform, shop_name, COUNT(*) as cnt FROM merged_orders "
                "WHERE order_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) "
                "GROUP BY platform, shop_name")
            plat_rows = cur.fetchall()
            plat_map = {}; platform_total = 0
            for r in plat_rows:
                p = r['platform'] or '未知'
                if p not in plat_map:
                    plat_map[p] = {'name': p, 'shop1_orders': 0, 'shop2_orders': 0}
                cnt = int(r['cnt'] or 0); platform_total += cnt
                if '五四北' in (r['shop_name'] or ''):
                    plat_map[p]['shop1_orders'] = cnt
                else:
                    plat_map[p]['shop2_orders'] = cnt
            platform_chart = list(plat_map.values())
            shop_cards = [
                {'shop_name': '五四北店', 'label': '近30天', 'income': s1_total_income, 'orders': s1_total_orders},
                {'shop_name': '湖前店', 'label': '近30天', 'income': s2_total_income, 'orders': s2_total_orders},
                {'shop_name': '五四北店', 'label': '日均', 'income': s1_total_income / 30, 'orders': round(s1_total_orders / 30)},
                {'shop_name': '湖前店', 'label': '日均', 'income': s2_total_income / 30, 'orders': round(s2_total_orders / 30)},
            ]
            cur.execute(
                "SELECT m.name, m.unit, "
                "COALESCE(SUM(CASE WHEN ib.shop_id=1 THEN ib.balance END), 0) as shop1, "
                "COALESCE(SUM(CASE WHEN ib.shop_id=2 THEN ib.balance END), 0) as shop2 "
                "FROM materials m LEFT JOIN inventory_balance ib ON ib.material_id=m.id "
                "WHERE m.name LIKE '%鲜鸡%' OR m.name LIKE '%内排%' "
                "OR m.name LIKE '%乳鸽%' OR m.name LIKE '%鸡爪%' "
                "GROUP BY m.name, m.unit")
            inv_rows = cur.fetchall()
            inventory_rows = []
            for r in inv_rows:
                s1 = float(r['shop1'] or 0); s2 = float(r['shop2'] or 0)
                inventory_rows.append({'name': r['name'], 'unit': r['unit'] or '',
                    'shop1': s1, 'shop2': s2, 'total': s1 + s2})
    finally:
        conn.close()
    return render_template('shops_compare.html', date_labels=date_labels,
        shop1_income=shop1_income, shop2_income=shop2_income,
        platform_chart=platform_chart, platform_total=platform_total,
        shop_cards=shop_cards, inventory_rows=inventory_rows, now=datetime.now())


@app.route('/cost-analysis')
@login_required
def cost_analysis():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) as total_orders, COALESCE(SUM(total_amount),0) as total_amount, "
                "MIN(purchase_time) as min_time, MAX(purchase_time) as max_time "
                "FROM purchase_orders")
            kpi_row = cur.fetchone()
            total_orders = int(kpi_row['total_orders'] or 0)
            total_amount = float(kpi_row['total_amount'] or 0)
            min_time = kpi_row['min_time']; max_time = kpi_row['max_time']
            if min_time and max_time:
                months = max(1, (max_time.year - min_time.year) * 12 + max_time.month - min_time.month + 1)
            else:
                months = 1
            cur.execute(
                "SELECT r.material_name as name, r.quantity as qty, r.unit, "
                "m.unit_price, m.category as group_name "
                "FROM product_recipes r LEFT JOIN materials m ON r.material_id = m.id "
                "WHERE r.product_code = 'ROAST_CHICKEN_WHOLE' ORDER BY r.sort_order")
            bom_rows = cur.fetchall()
            if not bom_rows:
                cur.execute(
                    "SELECT r.material_name as name, r.quantity as qty, r.unit, "
                    "m.unit_price, m.category as group_name "
                    "FROM product_recipes r LEFT JOIN materials m ON r.material_id = m.id "
                    "ORDER BY r.sort_order LIMIT 20")
                bom_rows = cur.fetchall()
            bom_breakdown = []; bom_total = 0.0; group_costs = {}
            for b in bom_rows:
                raw_price = float(b['unit_price'] or 0); qty = float(b['qty'] or 0)
                mat_name = b['name'] or ''
                conv = UNIT_CONVERSION.get(mat_name, 1)
                up = raw_price / conv if conv > 0 else raw_price
                cost = up * qty; bom_total += cost
                grp = b['group_name'] or '其他'
                group_costs[grp] = group_costs.get(grp, 0) + cost
                bom_breakdown.append({'name': b['name'] or '', 'group': grp, 'qty': qty,
                    'unit': b['unit'] or '', 'unit_price': round(up, 4) if up > 0 else None,
                    'cost': cost, 'note': ''})
            cost_summary = []
            for grp, cost in sorted(group_costs.items(), key=lambda x: -x[1]):
                pct = round(cost / bom_total * 100, 1) if bom_total > 0 else 0
                cost_summary.append({'group': grp, 'cost': cost, 'pct': pct})
            cur.execute(
                "SELECT COALESCE(supplier_name, '未知供应商') as supplier, SUM(total_amount) as amt "
                "FROM purchase_orders GROUP BY supplier_name ORDER BY amt DESC")
            pie_rows = cur.fetchall()
            pie_labels = [r['supplier'] or '其他' for r in pie_rows]
            pie_values = [float(r['amt'] or 0) for r in pie_rows]
            pie_total = sum(pie_values)
            cur.execute(
                "SELECT DATE_FORMAT(purchase_time, '%%Y-%%m') as month, SUM(total_amount) as amount "
                "FROM purchase_orders GROUP BY month ORDER BY month")
            monthly = [{'month': r['month'], 'amount': float(r['amount'] or 0)} for r in cur.fetchall()]
            spice_cost = group_costs.get('调味料', group_costs.get('调料', 0))
            pkg_cost = group_costs.get('包装', group_costs.get('包装材料', 0))
            kpi = {'total_orders': total_orders, 'total_amount': total_amount, 'months': months,
                'bom_total': bom_total, 'spice_per_chicken': spice_cost, 'pkg_per_chicken': pkg_cost}
            cur.execute(
                "SELECT product_name as name, COUNT(*) as times, MAX(po.purchase_time) as last_date, "
                "purchase_unit, AVG(purchase_price) as avg_price, SUM(total_price) as total_amt "
                "FROM purchase_order_items poi JOIN purchase_orders po ON poi.order_no = po.order_no "
                "GROUP BY product_name, purchase_unit ORDER BY last_date DESC LIMIT 30")
            freq_raw = cur.fetchall()
            freq_rows = []
            for r in freq_raw:
                ld = r['last_date']
                if ld:
                    if isinstance(ld, datetime):
                        days_ago = (datetime.now() - ld).days; last_date_str = ld.strftime('%m/%d')
                    elif isinstance(ld, date):
                        days_ago = (date.today() - ld).days; last_date_str = ld.strftime('%m/%d')
                    else:
                        days_ago = None; last_date_str = str(ld)
                else:
                    days_ago = None; last_date_str = '-'
                freq_rows.append({'name': r['name'] or '', 'times': int(r['times'] or 0),
                    'last_date': last_date_str, 'days_ago': days_ago,
                    'purchase_unit': r['purchase_unit'] or '',
                    'avg_price': float(r['avg_price'] or 0) if r['avg_price'] else None,
                    'total_amt': float(r['total_amt'] or 0)})
            cur.execute(
                "SELECT dps.date, SUM(dps.chicken_qty) as chicken_qty, "
                "COALESCE((SELECT SUM(expected_income) FROM daily_revenues WHERE date=dps.date), 0) as expected_income "
                "FROM daily_product_stats dps WHERE dps.chicken_qty > 0 "
                "GROUP BY dps.date ORDER BY dps.date DESC LIMIT 7")
            margin_raw = cur.fetchall()
            weekday_map = ['一', '二', '三', '四', '五', '六', '日']
            margin_cards = []
            for r in margin_raw:
                d = r['date']; chickens = int(r['chicken_qty'] or 0)
                income = float(r['expected_income'] or 0); cost = chickens * bom_total
                gross = income - cost; gm_pct = round(gross / income * 100, 1) if income > 0 else None
                d_str = d.strftime('%m/%d') if isinstance(d, date) else str(d)
                wd = weekday_map[d.weekday()] if isinstance(d, date) else ''
                margin_cards.append({'date': d_str, 'weekday': wd, 'chickens': chickens,
                    'income': income, 'cost': cost, 'gross': gross, 'gm_pct': gm_pct})
            cur.execute(
                "SELECT product_name as name, SUM(total_price) as amt "
                "FROM purchase_order_items WHERE category_name LIKE '%%包装%%' "
                "GROUP BY product_name ORDER BY amt DESC LIMIT 10")
            pkg_detail = [{'name': r['name'], 'amt': float(r['amt'] or 0)} for r in cur.fetchall()]
    finally:
        conn.close()
    return render_template('cost_analysis.html', kpi=kpi, monthly=monthly,
        pie_labels=pie_labels, pie_values=pie_values, pie_total=pie_total,
        cost_summary=cost_summary, bom_breakdown=bom_breakdown, bom_total=bom_total,
        freq_rows=freq_rows, margin_cards=margin_cards, pkg_detail=pkg_detail, now=datetime.now())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5006, debug=False)
