import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, make_response
from flask_cors import CORS
import sys
import hashlib
import hmac
import base64
import requests
import time
import asyncio

# Tambahkan path ke db folder
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from db.app import Database

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration
TUNNEL_URL = os.getenv('TUNNEL_URL', 'http://localhost:3000')
GITHUB_PAGES_URL = os.getenv('GITHUB_PAGES_URL', '')
DB_PATH = os.getenv('DB_PATH', '/root/tunnel-static/users.db')
STATIC_DIR = Path('/root/tunnel-static')

# Ensure static directory exists
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Initialize database
db = Database(DB_PATH)

# Wallet address untuk menerima pembayaran
WEB_ADDRESS = os.getenv('WEB_ADDRESS', '')

# TON Center API Key
TONCENTER_API_KEY = os.getenv('TONCENTER_API_KEY', '')
PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')
PRIVATE_KEY_BYTES = bytes.fromhex(PRIVATE_KEY) if PRIVATE_KEY else None

# Cek ketersediaan library TON
try:
    from pytoniq import begin_cell, Address, WalletV5R1, WalletV5R2
    from pytoniq_core import Cell
    TON_LIB_AVAILABLE = True
    W5_AVAILABLE = True
    print("✅ pytoniq library tersedia untuk W5")
except ImportError:
    TON_LIB_AVAILABLE = False
    W5_AVAILABLE = False
    print("⚠️ pytoniq tidak terinstall. Install dengan: pip install pytoniq pytoniq-core")
    print("⚠️ W5 withdraw tidak akan berfungsi tanpa pytoniq")

# ==================== ENDPOINT UNTUK MEMBUAT PAYLOAD ====================

@app.route('/api/create-payload', methods=['POST'])
def create_payload():
    """Buat payload yang valid untuk TON Connect"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    
    # Validasi
    if amount_ton < 0.1:
        return jsonify({'success': False, 'error': 'Minimum deposit 0.1 TON'}), 400
    
    # Get user dari database
    user = db.get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Buat memo dengan format yang jelas
    timestamp = int(datetime.now().timestamp())
    memo_plain = f"deposit:{telegram_id}:{timestamp}"
    
    # Buat payload menggunakan pytoniq (jika tersedia)
    if TON_LIB_AVAILABLE:
        try:
            # Buat Cell dengan comment
            # Format yang benar untuk text comment di TON
            cell = begin_cell() \
                .store_uint(0, 32) \
                .store_string(memo_plain) \
                .end_cell()
            
            # Encode cell ke Base64 (Bag of Cells)
            payload_base64 = base64.b64encode(cell.to_boc()).decode('utf-8')
            
            print(f"✅ Payload created with pytoniq: {payload_base64[:50]}...")
            
        except Exception as e:
            print(f"❌ Error creating cell with pytoniq: {e}")
            # Fallback ke metode sederhana jika pytoniq error
            memo_bytes = memo_plain.encode('utf-8')
            # Tambahkan prefix untuk text comment (0x00000000 dalam hex = 4 byte 0)
            comment_prefix = b'\x00\x00\x00\x00'
            full_bytes = comment_prefix + memo_bytes
            payload_base64 = base64.b64encode(full_bytes).decode('utf-8')
            print(f"⚠️ Using fallback payload method")
    else:
        # Fallback jika pytoniq tidak terinstall
        # Format: 4 byte 0 (untuk text comment) + memo
        memo_bytes = memo_plain.encode('utf-8')
        comment_prefix = b'\x00\x00\x00\x00'
        full_bytes = comment_prefix + memo_bytes
        payload_base64 = base64.b64encode(full_bytes).decode('utf-8')
        print(f"⚠️ Using fallback payload (pytoniq not installed)")
    
    # Konversi amount ke nano
    amount_nano = str(int(amount_ton * 1_000_000_000))
    
    # Simpan ke database tracking (tanpa transaction_hash dulu)
    if user:
        db.save_transaction(
            user_id=user['id'],
            transaction_hash=None,
            amount_ton=amount_ton,
            from_address=None,
            to_address=WEB_ADDRESS,
            memo=memo_plain,
            transaction_type='deposit'
        )
    
    # Log untuk debugging
    print(f"📤 Created payload for user {telegram_id}:")
    print(f"   Amount: {amount_ton} TON ({amount_nano} nano)")
    print(f"   Memo (plain): {memo_plain}")
    print(f"   Payload length: {len(payload_base64)} chars")
    print(f"   Payload (first 30): {payload_base64[:30]}...")
    
    return jsonify({
        'success': True,
        'transaction': {
            'address': WEB_ADDRESS,
            'amount': amount_nano,
            'payload': payload_base64
        },
        'memo_plain': memo_plain
    })

# ==================== ENDPOINT WITHDRAW UNTUK W5 ====================

@app.route('/api/withdraw-w5', methods=['POST'])
def withdraw_w5():
    """Withdraw otomatis untuk wallet W5 menggunakan pytoniq"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    destination_address = data.get('destination_address')
    
    # Validasi input
    if amount_ton < 0.1:
        return jsonify({'success': False, 'error': 'Minimum withdraw 0.1 TON'}), 400
    
    if not destination_address or len(destination_address) < 30:
        return jsonify({'success': False, 'error': 'Alamat tujuan tidak valid'}), 400
    
    # Cek user
    user = db.get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User tidak ditemukan'}), 404
    
    # Cek saldo
    current_balance = db.get_user_balance(telegram_id)
    if current_balance < amount_ton:
        return jsonify({
            'success': False, 
            'error': f'Saldo tidak cukup. Anda memiliki {current_balance} TON'
        }), 400
    
    # Validasi API Key dan Private Key
    if not TONCENTER_API_KEY:
        return jsonify({'success': False, 'error': 'API Key TON Center tidak dikonfigurasi'}), 500
    
    if not PRIVATE_KEY_BYTES:
        return jsonify({'success': False, 'error': 'Private Key tidak dikonfigurasi'}), 500
    
    if not W5_AVAILABLE:
        return jsonify({'success': False, 'error': 'pytoniq tidak terinstall untuk W5'}), 500
    
    try:
        print(f"\n🔄 Processing W5 withdraw for user {telegram_id}")
        print(f"   Amount: {amount_ton} TON")
        print(f"   To: {destination_address}")
        print(f"   From: {WEB_ADDRESS}")
        
        # Buat fungsi async untuk handle W5
        async def process_w5_withdraw():
            nonlocal amount_ton, destination_address, telegram_id, user
            
            # Buat wallet W5 dari private key
            # Coba dengan W5R1 dulu
            wallet = None
            try:
                wallet = await WalletV5R1.from_private_key(
                    private_key=PRIVATE_KEY_BYTES,
                    workchain=0
                )
                print("✅ Using WalletV5R1")
            except Exception as e1:
                print(f"⚠️ WalletV5R1 error: {e1}")
                try:
                    # Fallback ke W5R2
                    wallet = await WalletV5R2.from_private_key(
                        private_key=PRIVATE_KEY_BYTES,
                        workchain=0
                    )
                    print("✅ Using WalletV5R2")
                except Exception as e2:
                    print(f"❌ WalletV5R2 error: {e2}")
                    raise Exception("Tidak bisa membuat wallet W5 dari private key")
            
            # Dapatkan seqno
            try:
                seqno = await wallet.seqno()
                print(f"📊 Seqno: {seqno}")
            except:
                seqno = 0
                print(f"⚠️ Gagal get seqno, pakai 0")
            
            # Buat comment/memo
            timestamp = int(time.time())
            comment = f"wd_{telegram_id[-6:]}_{timestamp}"
            
            # Buat payload dengan comment
            comment_bytes = comment.encode('utf-8')
            payload_cell = begin_cell() \
                .store_uint(0, 32) \
                .store_bytes(comment_bytes) \
                .end_cell()
            
            # Konversi amount ke nanoTON
            amount_nano = int(amount_ton * 1_000_000_000)
            
            print(f"📤 Sending {amount_ton} TON ({amount_nano} nano)")
            print(f"💬 Comment: {comment}")
            
            # Buat transfer
            transfer = await wallet.transfer(
                destination=destination_address,
                amount=amount_nano,
                body=payload_cell,
                seqno=seqno
            )
            
            # Kirim ke blockchain via TON Center
            boc_b64 = transfer.to_boc().base64()
            
            send_response = requests.post(
                'https://toncenter.com/api/v2/sendBoc',
                data={'boc': boc_b64},
                headers={'X-API-Key': TONCENTER_API_KEY},
                timeout=30
            )
            
            send_result = send_response.json()
            print(f"📡 TON Center response: {send_result}")
            
            if send_result.get('ok'):
                # Generate transaction hash
                tx_hash = hashlib.sha256(transfer.to_boc()).hexdigest()
                
                return {
                    'success': True,
                    'transaction_hash': tx_hash,
                    'amount': amount_ton,
                    'to_address': destination_address,
                    'message': f'✅ Withdraw {amount_ton} TON berhasil dikirim!'
                }
            else:
                return {
                    'success': False,
                    'error': f'Gagal mengirim: {send_result.get("error", "Unknown error")}'
                }
        
        # Jalankan fungsi async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(process_w5_withdraw())
        loop.close()
        
        if result['success']:
            # Simpan di database
            tx_id = db.save_transaction(
                user_id=user['id'],
                transaction_hash=result['transaction_hash'],
                amount_ton=amount_ton,
                from_address=WEB_ADDRESS,
                to_address=destination_address,
                memo=f"wd_{telegram_id[-6:]}_{int(time.time())}",
                transaction_type='withdraw'
            )
            
            # Catat di withdraw_requests
            with db.get_connection() as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS withdraw_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        telegram_id TEXT,
                        amount_ton REAL,
                        destination_address TEXT,
                        status TEXT DEFAULT 'completed',
                        transaction_hash TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                conn.execute('''
                    INSERT INTO withdraw_requests 
                    (user_id, telegram_id, amount_ton, destination_address, status, transaction_hash)
                    VALUES (?, ?, ?, ?, 'completed', ?)
                ''', (user['id'], telegram_id, amount_ton, destination_address, result['transaction_hash']))
                conn.commit()
            
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        print(f"❌ Withdraw error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Error: {str(e)}'
        }), 500


# ==================== CEK SALDO WALLET ====================

@app.route('/api/check-balance')
def check_balance():
    """Cek saldo wallet"""
    try:
        response = requests.get(
            f'https://toncenter.com/api/v2/getAddressBalance',
            params={'address': WEB_ADDRESS},
            headers={'X-API-Key': TONCENTER_API_KEY},
            timeout=10
        )
        
        data = response.json()
        if data.get('ok'):
            balance_nano = int(data['result'])
            balance_ton = balance_nano / 1_000_000_000
            return jsonify({
                'success': True,
                'balance_ton': balance_ton,
                'balance_nano': balance_nano,
                'address': WEB_ADDRESS
            })
        else:
            return jsonify({'success': False, 'error': data.get('error')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ==================== WITHDRAW HISTORY ====================

@app.route('/api/withdraw-history/<telegram_id>')
def get_withdraw_history(telegram_id):
    """Get user withdraw history"""
    try:
        with db.get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS withdraw_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    telegram_id TEXT,
                    amount_ton REAL,
                    destination_address TEXT,
                    status TEXT DEFAULT 'pending',
                    transaction_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP
                )
            ''')
            
            cursor = conn.execute('''
                SELECT * FROM withdraw_requests 
                WHERE telegram_id = ?
                ORDER BY created_at DESC
                LIMIT 20
            ''', (telegram_id,))
            
            requests = [dict(row) for row in cursor.fetchall()]
            return jsonify({'success': True, 'requests': requests})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== SEMUA ENDPOINT YANG SUDAH ADA ====================

@app.route('/tonconnect-manifest.json')
def tonconnect_manifest():
    """Serve TON Connect manifest file"""
    manifest = {
        "url": TUNNEL_URL,
        "name": "Marketplace NFT Testing",
        "iconUrl": f"{GITHUB_PAGES_URL}/images/icon-web.png",
        "termsOfUseUrl": f"{TUNNEL_URL}/terms",
        "privacyPolicyUrl": f"{TUNNEL_URL}/privacy"
    }
    
    response = make_response(jsonify(manifest))
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/terms')
def terms():
    """Terms of use page"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Terms of Use</title></head>
    <body>
        <h1>Terms of Use</h1>
        <p>Ini adalah halaman syarat dan ketentuan untuk testing.</p>
    </body>
    </html>
    """

@app.route('/privacy')
def privacy():
    """Privacy policy page"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Privacy Policy</title></head>
    <body>
        <h1>Privacy Policy</h1>
        <p>Ini adalah halaman kebijakan privasi untuk testing.</p>
    </body>
    </html>
    """

@app.route('/api/user/<telegram_id>')
def get_user(telegram_id):
    """Get user data from database"""
    user = db.get_user(telegram_id)
    if user:
        return jsonify({
            'success': True,
            'user': {
                'telegram_id': user[1],
                'telegram_username': user[2],
                'telegram_first_name': user[3],
                'telegram_last_name': user[4],
                'telegram_photo_url': user[5],
                'wallet_address': user[6],
                'created_at': user[7]
            }
        })
    return jsonify({'success': False, 'error': 'User not found'}), 404

@app.route('/api/user', methods=['POST'])
def save_user():
    """Save or update user data"""
    data = request.json
    user_id = db.save_user(
        telegram_id=data.get('telegram_id'),
        telegram_username=data.get('telegram_username'),
        telegram_first_name=data.get('telegram_first_name'),
        telegram_last_name=data.get('telegram_last_name'),
        telegram_photo_url=data.get('telegram_photo_url'),
        wallet_address=data.get('wallet_address')
    )
    return jsonify({'success': True, 'user_id': user_id})

@app.route('/api/user/wallet', methods=['POST'])
def update_wallet():
    """Update user's wallet address"""
    data = request.json
    db.update_wallet_address(
        telegram_id=data.get('telegram_id'),
        wallet_address=data.get('wallet_address')
    )
    return jsonify({'success': True})

@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'tunnel_url': TUNNEL_URL
    })

@app.route('/api/balance/<telegram_id>')
def get_balance(telegram_id):
    """Get user balance"""
    balance = db.get_user_balance(telegram_id)
    return jsonify({
        'success': True,
        'balance': balance,
        'formatted': f"{balance} TON"
    })

@app.route('/api/transactions/<telegram_id>')
def get_transactions(telegram_id):
    """Get user transactions"""
    limit = request.args.get('limit', 20, type=int)
    transactions = db.get_user_transactions(telegram_id, limit)
    return jsonify({
        'success': True,
        'transactions': transactions
    })

@app.route('/api/deposit-info')
def deposit_info():
    """Get deposit information"""
    return jsonify({
        'success': True,
        'web_address': WEB_ADDRESS,
        'min_deposit': 0.1,
        'memo_required': False
    })

@app.route('/api/verify-transaction', methods=['POST'])
def verify_transaction():
    """Verify and record a transaction"""
    data = request.json
    telegram_id = data.get('telegram_id')
    transaction_hash = data.get('transaction_hash')
    amount_ton = data.get('amount_ton')
    from_address = data.get('from_address')
    memo = data.get('memo', '')
    
    # Get user from database
    user = db.get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Save transaction
    tx_id = db.save_transaction(
        user_id=user['id'],
        transaction_hash=transaction_hash,
        amount_ton=amount_ton,
        from_address=from_address,
        to_address=WEB_ADDRESS,
        memo=memo,
        transaction_type='deposit'
    )
    
    if tx_id:
        return jsonify({
            'success': True,
            'transaction_id': tx_id,
            'message': 'Transaction recorded, waiting for confirmation'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Transaction already exists'
        }), 400

@app.route('/api/webhook/ton', methods=['POST'])
def ton_webhook():
    data = request.json
    return jsonify({'success': True, 'message': 'Webhook received'})

# Optional: Serve static files if needed locally
@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files from STATIC_DIR"""
    return send_from_directory(STATIC_DIR, filename)

@app.route('/api/create-deposit-transaction', methods=['POST'])
def create_deposit_transaction():
    """Create a properly formatted transaction message for deposit"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    
    # Validasi
    if amount_ton < 0.1:
        return jsonify({'success': False, 'error': 'Minimum deposit 0.1 TON'}), 400
    
    # Get user dari database
    user = db.get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # 1️⃣ BUAT MEMO DENGAN FORMAT YANG SANGAT SEDERHANA
    # Hindari karakter khusus, gunakan hanya alfanumerik dan underscore
    timestamp = int(datetime.now().timestamp())
    # Format: deposit_USERID_TIMESTAMP
    # Contoh: deposit_123456789_1234567890
    memo_plain = f"deposit_{telegram_id}_{timestamp}"
    
    # 2️⃣ VALIDASI PANJANG MEMO
    # Pastikan tidak terlalu panjang (maks 120 karakter setelah di-encode)
    if len(memo_plain) > 80:
        # Gunakan hash jika terlalu panjang
        memo_hash = hashlib.sha256(memo_plain.encode()).hexdigest()[:16]
        memo_plain = f"dep_{telegram_id[-4:]}_{memo_hash}"
    
    # 3️⃣ ENCODE KE BASE64 DENGAN METHOD YANG PALING AMAN
    # Method 1: encode string ke bytes, lalu ke base64
    memo_bytes = memo_plain.encode('utf-8')
    memo_base64 = base64.b64encode(memo_bytes).decode('utf-8')
    
    # 4️⃣ VALIDASI BASE64 (harusnya selalu valid, tapi kita cek)
    try:
        # Coba decode kembali untuk memastikan
        decoded = base64.b64decode(memo_base64).decode('utf-8')
        if decoded != memo_plain:
            raise ValueError("Encode/decode mismatch")
    except Exception as e:
        # Fallback ke encoding yang lebih sederhana
        memo_base64 = base64.b64encode(memo_plain.encode('ascii', errors='ignore')).decode()
    
    # 5️⃣ KONVERSI AMOUNT KE NANOTONS (WAJIB STRING)
    amount_nano = str(int(amount_ton * 1_000_000_000))
    
    # 6️⃣ BUAT MESSAGE SESUAI FORMAT TON CONNECT
    # Perhatikan: HANYA field address, amount, payload
    transaction_message = {
        "address": WEB_ADDRESS,
        "amount": amount_nano,
        "payload": memo_base64
    }
    
    # Simpan ke database (tanpa transaction_hash dulu)
    if user:
        db.save_transaction(
            user_id=user['id'],
            transaction_hash=None,
            amount_ton=amount_ton,
            from_address=None,
            to_address=WEB_ADDRESS,
            memo=memo_plain,  # Simpan plain version
            transaction_type='deposit'
        )
    
    # Log untuk debugging
    print(f"📤 Created transaction for user {telegram_id}:")
    print(f"   Amount: {amount_ton} TON ({amount_nano} nano)")
    print(f"   Memo (plain): {memo_plain}")
    print(f"   Memo (base64): {memo_base64}")
    print(f"   Payload length: {len(memo_base64)} chars")
    
    return jsonify({
        'success': True,
        'transaction_data': transaction_message,
        'memo_plain': memo_plain
    })

@app.route('/api/create-tonpay-transaction', methods=['POST'])
def create_tonpay_transaction():
    """Buat transaksi menggunakan TON Pay API (sesuai dokumentasi resmi)"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    sender_address = data.get('sender_address')  # Dari TON Connect
    
    # Validasi
    if amount_ton < 0.1:
        return jsonify({'success': False, 'error': 'Minimum deposit 0.1 TON'}), 400
    
    # Get user dari database
    user = db.get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Di sini seharusnya panggil createTonPayTransfer dari JavaScript
    # TAPI karena Python, kita perlu:
    
    # OPSI 1: Buat child process untuk menjalankan Node.js script
    # OPSI 2: Gunakan API eksternal (recommended)
    
    # Untuk sementara, kita generate reference di backend
    import hashlib
    timestamp = int(datetime.now().timestamp())
    reference = f"deposit_{telegram_id}_{timestamp}"
    body_hash = hashlib.sha256(reference.encode()).hexdigest()
    
    # Simpan tracking data
    with db.get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS payment_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT UNIQUE,
                body_base64_hash TEXT,
                telegram_id TEXT,
                amount REAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            INSERT OR IGNORE INTO payment_tracking (reference, body_base64_hash, telegram_id, amount)
            VALUES (?, ?, ?, ?)
        ''', (reference, body_hash, telegram_id, amount_ton))
        conn.commit()
    
    # Format message sesuai TON Connect spec
    message = {
        "address": WEB_ADDRESS,
        "amount": str(int(amount_ton * 1_000_000_000)),  # Dalam nanoTON
        "payload": None  # Akan diisi oleh frontend dengan createTonPayTransfer
    }
    
    return jsonify({
        'success': True,
        'message': message,
        'reference': reference,
        'bodyBase64Hash': body_hash
    })

@app.route('/api/store-payment-tracking', methods=['POST'])
def store_payment_tracking():
    """Store payment tracking data before sending transaction"""
    data = request.json
    reference = data.get('reference')
    bodyBase64Hash = data.get('bodyBase64Hash')
    telegram_id = data.get('telegram_id')
    amount = data.get('amount')
    
    # Simpan ke database tracking
    with db.get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS payment_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT UNIQUE,
                body_base64_hash TEXT,
                telegram_id TEXT,
                amount REAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            INSERT INTO payment_tracking (reference, body_base64_hash, telegram_id, amount)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(reference) DO NOTHING
        ''', (reference, bodyBase64Hash, telegram_id, amount))
        conn.commit()
    
    return jsonify({'success': True})


# ==================== MAIN ====================
if __name__ == '__main__':
    print(f"🚀 Flask server running on {TUNNEL_URL}")
    print(f"📝 Manifest URL: {TUNNEL_URL}/tonconnect-manifest.json")
    print(f"💾 Database path: {DB_PATH}")
    print(f"💰 Web Address: {WEB_ADDRESS}")
    print(f"🔑 Private Key: {'✅ Tersedia' if PRIVATE_KEY_BYTES else '❌ Tidak ada'}")
    print(f"🔑 TON Center API: {'✅ Tersedia' if TONCENTER_API_KEY else '❌ Tidak ada'}")
    print(f"📦 TON Library: {'✅ pytoniq tersedia' if TON_LIB_AVAILABLE else '❌ Tidak ada'}")
    print(f"📦 W5 Support: {'✅ Tersedia' if W5_AVAILABLE else '❌ Tidak ada'}")
    
    if not TON_LIB_AVAILABLE:
        print("⚠️ Install pytoniq untuk payload dan W5: pip install pytoniq pytoniq-core")
    
    print(f"📊 Endpoints available:")
    print(f"   - /api/balance/<telegram_id>")
    print(f"   - /api/transactions/<telegram_id>")
    print(f"   - /api/deposit-info")
    print(f"   - /api/verify-transaction")
    print(f"   - /api/create-payload")
    print(f"   - /api/withdraw-w5 (NEW - untuk W5)")
    print(f"   - /api/withdraw-history/<telegram_id>")
    print(f"   - /api/check-balance")
    
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', 3000)),
        debug=os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    )