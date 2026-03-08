import sqlite3
import json
from datetime import datetime
from pathlib import Path

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id TEXT UNIQUE NOT NULL,
                    telegram_username TEXT,
                    telegram_first_name TEXT,
                    telegram_last_name TEXT,
                    telegram_photo_url TEXT,
                    wallet_address TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    session_id TEXT UNIQUE,
                    wallet_connected BOOLEAN DEFAULT 0,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')

            # DROP tabel transactions yang lama (jika ada) dan buat ulang
            conn.execute('DROP TABLE IF EXISTS transactions')
            
            conn.execute('''
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    transaction_hash TEXT UNIQUE,
                    amount_ton REAL,
                    amount_nano TEXT,
                    from_address TEXT,
                    to_address TEXT,
                    memo TEXT,
                    status TEXT DEFAULT 'pending',
                    nft_id TEXT,
                    transaction_type TEXT DEFAULT 'deposit',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            conn.commit()
            print(f"✅ Database reinitialized at {self.db_path}")
    
    def save_user(self, telegram_id, telegram_username=None, 
                  telegram_first_name=None, telegram_last_name=None,
                  telegram_photo_url=None, wallet_address=None):
        """Save or update user"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO users (
                    telegram_id, telegram_username, telegram_first_name,
                    telegram_last_name, telegram_photo_url, wallet_address
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    telegram_username = excluded.telegram_username,
                    telegram_first_name = excluded.telegram_first_name,
                    telegram_last_name = excluded.telegram_last_name,
                    telegram_photo_url = excluded.telegram_photo_url,
                    wallet_address = excluded.wallet_address,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            ''', (
                telegram_id, telegram_username, telegram_first_name,
                telegram_last_name, telegram_photo_url, wallet_address
            ))
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else None
    
    def get_user(self, telegram_id):
        """Get user by telegram ID"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM users WHERE telegram_id = ?
            ''', (telegram_id,))
            return cursor.fetchone()
    
    def update_wallet_address(self, telegram_id, wallet_address):
        """Update user's wallet address"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE users 
                SET wallet_address = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            ''', (wallet_address, telegram_id))
            conn.commit()
    
    def create_session(self, user_id, session_id):
        """Create new session"""
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO sessions (user_id, session_id)
                VALUES (?, ?)
            ''', (user_id, session_id))
            conn.commit()
    
    def update_session_wallet(self, session_id, wallet_connected):
        """Update session wallet status"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE sessions 
                SET wallet_connected = ?, last_active = CURRENT_TIMESTAMP
                WHERE session_id = ?
            ''', (wallet_connected, session_id))
            conn.commit()
    
    def save_transaction(self, user_id, transaction_hash, amount_ton, from_address, to_address, memo="", nft_id=None, transaction_type="deposit"):
        """Save transaction record - langsung confirmed untuk deposit"""
        with self.get_connection() as conn:
            # Convert TON to nano if needed
            amount_nano = str(int(amount_ton * 1_000_000_000))
            
            cursor = conn.execute('''
                INSERT INTO transactions (
                    user_id, transaction_hash, amount_ton, amount_nano, 
                    from_address, to_address, memo, nft_id, transaction_type, status, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(transaction_hash) DO NOTHING
                RETURNING id
            ''', (
                user_id, transaction_hash, amount_ton, amount_nano,
                from_address, to_address, memo, nft_id, transaction_type, 'confirmed'  # Langsung confirmed
            ))
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else None
    
    def confirm_transaction(self, transaction_hash):
        """Mark transaction as confirmed"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE transactions 
                SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
                WHERE transaction_hash = ?
            ''', (transaction_hash,))
            conn.commit()
    
    def get_user_transactions(self, telegram_id, limit=20):
        """Get all transactions for a user with limit"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT t.* FROM transactions t
                JOIN users u ON t.user_id = u.id
                WHERE u.telegram_id = ?
                ORDER BY t.created_at DESC
                LIMIT ?
            ''', (telegram_id, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_user_balance(self, telegram_id):
        """Calculate user's total balance from confirmed transactions"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute('''
                    SELECT COALESCE(SUM(amount_ton), 0) as total_balance
                    FROM transactions t
                    JOIN users u ON t.user_id = u.id
                    WHERE u.telegram_id = ? 
                    AND t.status = 'confirmed'
                    AND t.transaction_type IN ('deposit', 'payment_received')
                ''', (telegram_id,))
                result = cursor.fetchone()
                return float(result[0]) if result else 0.0
        except Exception as e:
            print(f"Error getting balance: {e}")
            return 0.0