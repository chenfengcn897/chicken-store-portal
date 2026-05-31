#!/usr/bin/env python3
"""备份并去重 product_recipes 表中重复产品编码的记录"""
import pymysql

conn = pymysql.connect(
    host='127.0.0.1', port=3306, user='root', password='ChickenStore2026!',
    database='chicken_store', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
)
try:
    with conn.cursor() as cur:
        # 1. 备份
        cur.execute("CREATE TABLE IF NOT EXISTS product_recipes_bak_20260531 AS SELECT * FROM product_recipes")
        conn.commit()
        print("Backup created: product_recipes_bak_20260531")

        # 2. 查询备份前统计
        cur.execute("""
            SELECT product_code, product_name, COUNT(*) as cnt
            FROM product_recipes
            WHERE product_code IN (
                'ROAST_CHICKEN_WHOLE','ROAST_CHICKEN_HALF',
                'SESAME_CHICKEN_WHOLE','SESAME_CHICKEN_HALF'
            )
            GROUP BY product_code, product_name
            ORDER BY cnt DESC
        """)
        print("\n=== Before dedup ===")
        for r in cur.fetchall():
            print(f"  {r['product_code']} ({r['product_name']}): {r['cnt']} records")

        # 3. 去重：保留每组 product_code+product_name 中 id 最大的那条
        cur.execute("""
            DELETE r1 FROM product_recipes r1
            INNER JOIN product_recipes r2
            WHERE r1.product_code = r2.product_code
              AND r1.product_name = r2.product_name
              AND r1.id < r2.id
        """)
        deleted = cur.rowcount
        print(f"\nDeleted {deleted} duplicate rows")
        conn.commit()

        # 4. 验证
        cur.execute("""
            SELECT product_code, product_name, COUNT(*) as cnt
            FROM product_recipes
            WHERE product_code IN (
                'ROAST_CHICKEN_WHOLE','ROAST_CHICKEN_HALF',
                'SESAME_CHICKEN_WHOLE','SESAME_CHICKEN_HALF'
            )
            GROUP BY product_code, product_name
            ORDER BY cnt DESC
        """)
        print("\n=== After dedup ===")
        dupes_found = False
        for r in cur.fetchall():
            print(f"  {r['product_code']} ({r['product_name']}): {r['cnt']} records")
            if r['cnt'] > 1:
                dupes_found = True

        if dupes_found:
            print("\n❌ Some products still have duplicates!")
            exit(1)
        else:
            print(f"\n✅ Dedup complete: {deleted} duplicate rows removed, all products now have unique (product_code, product_name) pairs")

        # 5. 确认备份表行数
        cur.execute("SELECT COUNT(*) as cnt FROM product_recipes_bak_20260531")
        bak_rows = cur.fetchone()['cnt']
        print(f"Backup table product_recipes_bak_20260531 has {bak_rows} rows (safe to restore if needed)")

finally:
    conn.close()
