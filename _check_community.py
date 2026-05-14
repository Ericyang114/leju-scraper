# -*- coding: utf-8 -*-
import sqlite3, os, json
os.chdir(r'D:\claude code\leju_scraper')
conn = sqlite3.connect('leju.db')

result = {}

# Top communities by count
rows = conn.execute("""
    SELECT community, COUNT(*) as cnt
    FROM transactions
    WHERE community IS NOT NULL
    GROUP BY community
    ORDER BY cnt DESC
    LIMIT 50
""").fetchall()
result['top_communities'] = [[r[0], r[1]] for r in rows]

# Transactions on 民有東路
rows2 = conn.execute("""
    SELECT transaction_date, community, address, floor, total_price, unit_price
    FROM transactions
    WHERE address LIKE '%民有東路%'
    ORDER BY transaction_date DESC
    LIMIT 20
""").fetchall()
result['minyo_road'] = [[r[0],r[1],r[2],r[3],r[4],r[5]] for r in rows2]

with open(r'D:\claude code\leju_scraper\_check_out.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

conn.close()
print('done')
