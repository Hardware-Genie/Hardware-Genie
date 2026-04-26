#!/usr/bin/env python3
"""
Check main database for recent V-COLOR data
"""

import sqlite3
import os

def check_main_database():
    """Check the main application database"""
    db_path = 'instance/parts.db'
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if memory table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory'")
        if cursor.fetchone():
            # Get the most recent entries
            cursor.execute("""
                SELECT name, snapshot_date, price, timestamp, modules, speed, cas_latency, color
                FROM memory 
                ORDER BY timestamp DESC, snapshot_date DESC 
                LIMIT 10
            """)
            results = cursor.fetchall()
            
            print("Recent entries in main database (memory table):")
            print("-" * 80)
            for name, date, price, timestamp, modules, speed, cl, color in results:
                print(f"  Product: {name}")
                print(f"    Date: {date}, Price: ${price}, Timestamp: {timestamp}")
                print(f"    Modules: {modules}, Speed: {speed}, CL: {cl}, Color: {color}")
                print()
            
            # Look for V-COLOR specifically
            cursor.execute("""
                SELECT name, snapshot_date, price, timestamp
                FROM memory 
                WHERE name LIKE '%V-COLOR%'
                ORDER BY timestamp DESC
            """)
            vcolor_results = cursor.fetchall()
            
            print("V-COLOR entries in main database:")
            print("-" * 80)
            for name, date, price, timestamp in vcolor_results:
                print(f"  Product: {name}")
                print(f"    Date: {date}, Price: ${price}, Timestamp: {timestamp}")
                print()
        else:
            print("Memory table not found in main database")
        
        cursor.close()
        conn.close()
    else:
        print('Main database file does not exist')

if __name__ == "__main__":
    check_main_database()
