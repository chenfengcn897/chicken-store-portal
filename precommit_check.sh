#!/bin/bash
# Portal 预提交验证脚本
set -e
VENV=/home/ubuntu/chicken-store-portal/venv/bin/python3

echo "=== 1. 编译检查 ==="
$VENV -m py_compile /home/ubuntu/chicken-store-portal/app.py && echo "  OK"

echo "=== 2. 回归测试(14用例) ==="
$VENV /home/ubuntu/chicken-store/scripts_wrapper/regression_test_cost.py | tail -1 | grep -q "失败: 0" && echo "  OK" || { echo "  FAILED"; exit 1; }

echo "=== 3. Dashboard行数 ==="
$VENV -c "
import sys; sys.path.insert(0,'/home/ubuntu/chicken-store-portal')
import app; app._recipe_cache.clear(); app.app.testing=True
with app.app.test_client() as c:
    r=c.get('/dashboard')
    import re; rows=re.findall('<tr.*?hover.*?</tr>',r.data.decode(),re.DOTALL)
    assert len(rows)==4, f'Dashboard rows: {len(rows)}'
    print('  4 rows OK')
"

echo "=== 4. Portal全部页面200 ==="
for p in / /orders /recipes /logs /dashboard /revenue-dashboard /shops-compare /cost-analysis; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -b "auth_token=fxd2026" "http://localhost:5006$p")
    [ "$code" = "200" ] && echo "  OK $p" || { echo "  FAIL $p: $code"; exit 1; }
done

echo ""
echo "ALL CHECKS PASSED"
