# -*- coding: utf-8 -*-
import sqlite3, os, json
os.chdir(r'D:\claude code\leju_scraper')
conn = sqlite3.connect('leju.db')

# 1. 找家賀澄舍的 sid
rows = conn.execute("""
    SELECT sid, COUNT(*) FROM transactions
    WHERE community = '家賀澄舍'
    GROUP BY sid
""").fetchall()
print('家賀澄舍 sid:', rows)

# 2. 找出該生活圈名稱
if rows:
    sid = rows[0][0]
    sa = conn.execute("SELECT name FROM subareas WHERE sid=?", (sid,)).fetchone()
    print('生活圈:', sa)

    # 3. 每個月的資料量
    monthly = conn.execute("""
        SELECT SUBSTR(transaction_date,1,7) as ym, COUNT(*) as cnt
        FROM transactions WHERE sid=?
        GROUP BY ym ORDER BY ym DESC
        LIMIT 40
    """, (sid,)).fetchall()
    print('\n每月筆數（該生活圈）:')
    for r in monthly:
        flag = ' ← 超過20!!' if r[1] >= 20 else ''
        print(f'  {r[0]}  {r[1]} 筆{flag}')

conn.close()
