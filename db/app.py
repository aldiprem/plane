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
        """Initialize database tables with safe schema updates"""
        with self.get_connection() as conn:
            # Create users table
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
            
            # Create sessions table
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

            # Create transactions table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
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
            
            # Create withdraw_requests table if not exists
            conn.execute('''
                CREATE TABLE IF NOT EXISTS withdraw_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    telegram_id TEXT,
                    amount_ton REAL,
                    destination_address TEXT,
                    reference TEXT,
                    transaction_hash TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Create payment_tracking table if not exists
            conn.execute('''
                CREATE TABLE IF NOT EXISTS payment_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference TEXT UNIQUE,
                    body_base64_hash TEXT,
                    telegram_id TEXT,
                    amount REAL,
                    status TEXT DEFAULT 'pending',
                    transaction_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            
            # Now add missing columns using ALTER TABLE
            self._add_missing_columns(conn)
            
            print("✅ Database initialized with correct schema")
    
    def _add_missing_columns(self, conn):
        """Add missing columns to existing tables"""
        cursor = conn.cursor()
        
        # Check and add columns to withdraw_requests
        cursor.execute("PRAGMA table_info(withdraw_requests)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'reference' not in columns:
            try:
                conn.execute('ALTER TABLE withdraw_requests ADD COLUMN reference TEXT')
                print("✅ Added 'reference' column to withdraw_requests")
            except Exception as e:
                print(f"⚠️ Could not add reference column: {e}")
        
        if 'transaction_hash' not in columns:
            try:
                conn.execute('ALTER TABLE withdraw_requests ADD COLUMN transaction_hash TEXT')
                print("✅ Added 'transaction_hash' column to withdraw_requests")
            except Exception as e:
                print(f"⚠️ Could not add transaction_hash column: {e}")
        
        if 'processed_at' not in columns:
            try:
                conn.execute('ALTER TABLE withdraw_requests ADD COLUMN processed_at TIMESTAMP')
                print("✅ Added 'processed_at' column to withdraw_requests")
            except Exception as e:
                print(f"⚠️ Could not add processed_at column: {e}")
        
        # Check and add columns to payment_tracking
        cursor.execute("PRAGMA table_info(payment_tracking)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'transaction_hash' not in columns:
            try:
                conn.execute('ALTER TABLE payment_tracking ADD COLUMN transaction_hash TEXT')
                print("✅ Added 'transaction_hash' column to payment_tracking")
            except Exception as e:
                print(f"⚠️ Could not add transaction_hash column: {e}")
        
        if 'body_base64_hash' not in columns:
            try:
                conn.execute('ALTER TABLE payment_tracking ADD COLUMN body_base64_hash TEXT')
                print("✅ Added 'body_base64_hash' column to payment_tracking")
            except Exception as e:
                print(f"⚠️ Could not add body_base64_hash column: {e}")
        
        conn.commit()
    
    # ==================== USER METHODS ====================
    
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
    
    # ==================== SESSION METHODS ====================
    
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
    
    # ==================== TRANSACTION METHODS ====================
    
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
                from_address, to_address, memo, nft_id, transaction_type, 'confirmed'
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
    
    # ==================== WITHDRAW METHODS ====================
    
    def save_withdraw_request(self, user_id, telegram_id, amount_ton, destination_address):
        """Save withdraw request"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO withdraw_requests (user_id, telegram_id, amount_ton, destination_address)
                VALUES (?, ?, ?, ?)
                RETURNING id
            ''', (user_id, telegram_id, amount_ton, destination_address))
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else None
    
    def save_withdraw_request_with_reference(self, user_id, telegram_id, amount_ton, destination_address, reference):
        """Save withdraw request with reference"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO withdraw_requests 
                (user_id, telegram_id, amount_ton, destination_address, reference, status)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
            ''', (user_id, telegram_id, amount_ton, destination_address, reference, 'pending'))
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else None
    
    def get_withdraw_requests(self, telegram_id, limit=20):
        """Get user withdraw requests"""
        with self.get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM withdraw_requests 
                WHERE telegram_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (telegram_id, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def update_withdraw_request(self, request_id, transaction_hash, status='completed'):
        """Update withdraw request status"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE withdraw_requests 
                SET status = ?, transaction_hash = ?, processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, transaction_hash, request_id))
            conn.commit()
    
    def update_withdraw_request_by_reference(self, reference, transaction_hash, status='completed'):
        """Update withdraw request by reference"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE withdraw_requests 
                SET status = ?, transaction_hash = ?, processed_at = CURRENT_TIMESTAMP
                WHERE reference = ?
            ''', (status, transaction_hash, reference))
            conn.commit()
    
    def update_withdraw_request_with_hash(self, transaction_hash, telegram_id):
        """Update withdraw request with transaction hash"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE withdraw_requests 
                SET transaction_hash = ?, status = 'completed', processed_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
            ''', (transaction_hash, telegram_id))
            conn.commit()
    
    # ==================== PAYMENT TRACKING METHODS ====================
    
    def save_payment_tracking(self, reference, body_base64_hash, telegram_id, amount):
        """Save payment tracking data"""
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR IGNORE INTO payment_tracking 
                (reference, body_base64_hash, telegram_id, amount, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (reference, body_base64_hash, telegram_id, amount, 'pending'))
            conn.commit()
    
    def update_payment_tracking_status(self, reference, status='completed', transaction_hash=None):
        """Update payment tracking status"""
        with self.get_connection() as conn:
            conn.execute('''
                UPDATE payment_tracking 
                SET status = ?, transaction_hash = ?
                WHERE reference = ?
            ''', (status, transaction_hash, reference))
            conn.commit()