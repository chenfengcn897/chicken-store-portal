#!/bin/bash
# Portal 预提交验证脚本 v2
set -e
DIR=/home/ubuntu/chicken-store-portal
VENV=$DIR/venv/bin/python3

echo "=== 1. git diff ==="
cd $DIR && git diff --stat

echo "=== 2. 编译检查 ==="
$VENV -m py_compile $DIR/app.py && echo "  OK"

echo "=== 3. 回归测试(14用例) ==="
$VENV /home/ubuntu/chicken-store/scripts_wrapper/regression_test_cost.py | tail -1 | grep -q "失败: 0" && echo "  OK" || { echo "  FAIL"; exit 1; }

echo "=== 4. Dashboard完整性 ==="
$VENV -c "
import sys; sys.path.insert(0,'$DIR')
import app; app._recipe_cache.clear(); app.app.testing=True
with app.app.test_client() as c:
    r=c.get('/dashboard')
    import re; rows=re.findall('<tr.*?hover.*?</tr>',r.data.decode(),re.DOTALL)
    assert len(rows)==4, f'Rows: {len(rows)}'
    assert '360' in r.data.decode() or '安全线' in r.data.decode()
    print('  4 rows, 安全线 OK')
"

echo "=== 5. 全部页面200 ==="
for p in / /orders /recipes /logs /dashboard /revenue-dashboard /shops-compare /cost-analysis; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -b "auth_token=fxd2026" "http://localhost:5006$p")
    [ "$code" = "200" ] && echo "  OK $p" || { echo "  FAIL $p: $code"; exit 1; }
done

echo ""
echo "ALL CHECKS PASSED"
