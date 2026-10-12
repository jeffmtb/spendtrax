import sqlite3

conn = sqlite3.connect('spendtrax.db')
cursor = conn.cursor()

print("TOP 30 Personal & Household by Amount:")
print("="*100)
cursor.execute("""
    SELECT description, amount, account, check_number 
    FROM transactions 
    WHERE category = 'Personal & Household' 
    ORDER BY amount DESC 
    LIMIT 30
""")
for row in cursor.fetchall():
    desc, amount, account, check_num = row
    check_str = f"#{check_num}" if check_num else ""
    print(f"${amount:>10,.2f} | {account:<20} | {check_str:<7} | {desc[:55]}")

print("\n\nBREAKDOWN BY ACCOUNT:")
print("="*60)
cursor.execute("""
    SELECT account, COUNT(*), SUM(amount)
    FROM transactions 
    WHERE category = 'Personal & Household' 
    GROUP BY account
    ORDER BY SUM(amount) DESC
""")
for account, count, total in cursor.fetchall():
    print(f"{account:<20}: {count:>4} transactions, ${total:>12,.2f}")

conn.close()
