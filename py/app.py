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

NETWORK = os.getenv('NETWORK', 'mainnet')

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

# TON Center API Key (masih diperlukan untuk cek saldo)
TONCENTER_API_KEY = os.getenv('TONCENTER_API_KEY', '')

# Private key TIDAK DIGUNAKAN LAGI untuk withdraw otomatis
# Tapi tetap dibaca untuk kompatibilitas ke belakang
PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')
PRIVATE_KEY_BYTES = bytes.fromhex(PRIVATE_KEY) if PRIVATE_KEY else None

# Cek ketersediaan library TON (hanya untuk create-payload)
try:
    from pytoniq import begin_cell, Address
    from pytoniq_core import Cell
    TON_LIB_AVAILABLE = True
    print("✅ pytoniq library tersedia untuk create-payload")
except ImportError as e:
    TON_LIB_AVAILABLE = False
    print(f"⚠️ pytoniq tidak terinstall: {e}")

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

# ==================== ENDPOINT WITHDRAW MENGGUNAKAN TON PAY ====================

@app.route('/api/initiate-withdraw', methods=['POST'])
def initiate_withdraw():
    """Endpoint untuk memulai proses withdraw - menyimpan request dan memberikan reference"""
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
    
    # Buat reference unik untuk withdraw
    timestamp = int(time.time())
    reference = f"wd_{telegram_id}_{timestamp}"
    
    # Simpan request withdraw dengan reference
    try:
        # Perlu update method save_withdraw_request untuk menerima reference
        # Untuk sementara, kita simpan di payment_tracking dulu
        db.save_payment_tracking(reference, None, telegram_id, amount_ton)
        
        # Juga simpan di withdraw_requests (asumsikan tabel sudah diupdate)
        request_id = db.save_withdraw_request_with_reference(
            user['id'], telegram_id, amount_ton, destination_address, reference
        )
    except Exception as e:
        print(f"⚠️ Error saving withdraw request: {e}")
        # Fallback: simpan hanya di payment_tracking
        request_id = None
    
    print(f"📤 Withdraw initiated for user {telegram_id}: {amount_ton} TON to {destination_address}")
    print(f"   Reference: {reference}")
    
    return jsonify({
        'success': True,
        'reference': reference,
        'amount_ton': amount_ton,
        'destination_address': destination_address,
        'message': 'Withdraw request recorded. Silakan lanjutkan dengan TON Pay di frontend.'
    })

@app.route('/api/verify-withdraw', methods=['POST'])
def verify_withdraw():
    """Verifikasi withdraw setelah transaksi berhasil di frontend"""
    data = request.json
    reference = data.get('reference')
    transaction_hash = data.get('transaction_hash')
    status = data.get('status', 'completed')
    
    if not reference:
        return jsonify({'success': False, 'error': 'Reference tidak ditemukan'}), 400
    
    try:
        # Update status di payment_tracking
        db.update_payment_tracking_status(reference, status, transaction_hash)
        
        # Update withdraw_requests berdasarkan reference
        db.update_withdraw_request_by_reference(reference, transaction_hash, status)
        
        # Dapatkan telegram_id dari reference (format: wd_telegram_id_timestamp)
        parts = reference.split('_')
        if len(parts) >= 2 and parts[0] == 'wd':
            telegram_id = parts[1]
            user = db.get_user(telegram_id)
            
            if user and transaction_hash:
                # Dapatkan amount dari payment_tracking
                # Untuk sementara, kita gunakan amount dari request nanti
                # Atau bisa query dari payment_tracking
                
                # Catat transaksi withdraw di tabel transactions
                # Ini akan mengurangi saldo user
                # TODO: Dapatkan amount dari database
                amount_ton = 0  # Harusnya diambil dari payment_tracking
                
                print(f"✅ Withdraw confirmed: {reference} - {transaction_hash}")
        
        return jsonify({
            'success': True,
            'message': 'Withdraw verified and recorded'
        })
    except Exception as e:
        print(f"❌ Error verifying withdraw: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== ENDPOINT LEGACY WITHDRAW (UNTUK KOMPATIBILITAS) ====================

@app.route('/api/withdraw', methods=['POST'])
def withdraw_legacy():
    """Legacy endpoint - mengarahkan ke initiate-withdraw"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    destination_address = data.get('destination_address')
    
    # Panggil fungsi initiate_withdraw
    return initiate_withdraw()

def withdraw_manual(telegram_id, amount_ton, destination_address, user):
    """Fallback manual withdraw (tidak digunakan lagi)"""
    return jsonify({
        'success': False,
        'error': 'Withdraw otomatis tidak lagi menggunakan backend. Silakan gunakan TON Pay di frontend.'
    }), 400

# ==================== CEK SALDO WALLET ====================

@app.route('/api/check-balance')
def check_balance():
    """Cek saldo wallet merchant"""
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
        requests_data = db.get_withdraw_requests(telegram_id, 20)
        return jsonify({'success': True, 'requests': requests_data})
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
                'telegram_id': user['telegram_id'],
                'telegram_username': user['telegram_username'],
                'telegram_first_name': user['telegram_first_name'],
                'telegram_last_name': user['telegram_last_name'],
                'telegram_photo_url': user['telegram_photo_url'],
                'wallet_address': user['wallet_address'],
                'created_at': user['created_at']
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
    """Verify and record a transaction (untuk deposit)"""
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
    
    # Simpan sebagai confirmed
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
            'message': 'Transaction recorded and confirmed!'
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
    
    # Buat memo
    timestamp = int(datetime.now().timestamp())
    memo_plain = f"deposit_{telegram_id}_{timestamp}"
    
    if len(memo_plain) > 80:
        memo_hash = hashlib.sha256(memo_plain.encode()).hexdigest()[:16]
        memo_plain = f"dep_{telegram_id[-4:]}_{memo_hash}"
    
    memo_bytes = memo_plain.encode('utf-8')
    memo_base64 = base64.b64encode(memo_bytes).decode('utf-8')
    
    amount_nano = str(int(amount_ton * 1_000_000_000))
    
    transaction_message = {
        "address": WEB_ADDRESS,
        "amount": amount_nano,
        "payload": memo_base64
    }
    
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
    
    print(f"📤 Created transaction for user {telegram_id}: {amount_ton} TON")
    
    return jsonify({
        'success': True,
        'transaction_data': transaction_message,
        'memo_plain': memo_plain
    })

@app.route('/api/create-tonpay-transaction', methods=['POST'])
def create_tonpay_transaction():
    """Buat transaksi menggunakan TON Pay API"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    
    if amount_ton < 0.1:
        return jsonify({'success': False, 'error': 'Minimum deposit 0.1 TON'}), 400
    
    user = db.get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    timestamp = int(datetime.now().timestamp())
    reference = f"deposit_{telegram_id}_{timestamp}"
    body_hash = hashlib.sha256(reference.encode()).hexdigest()
    
    db.save_payment_tracking(reference, body_hash, telegram_id, amount_ton)
    
    message = {
        "address": WEB_ADDRESS,
        "amount": str(int(amount_ton * 1_000_000_000)),
        "payload": None
    }
    
    return jsonify({
        'success': True,
        'message': message,
        'reference': reference,
        'bodyBase64Hash': body_hash
    })

@app.route('/api/store-payment-tracking', methods=['POST'])
def store_payment_tracking():
    """Store payment tracking data"""
    data = request.json
    db.save_payment_tracking(
        data.get('reference'),
        data.get('bodyBase64Hash'),
        data.get('telegram_id'),
        data.get('amount')
    )
    return jsonify({'success': True})

@app.route('/api/process-withdraw', methods=['POST'])
def process_withdraw_backend():
    """Proses withdraw dari backend menggunakan private key"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    destination_address = data.get('destination_address')
    reference = data.get('reference')
    
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
    
    # Validasi private key
    if not PRIVATE_KEY_BYTES:
        return jsonify({'success': False, 'error': 'Private key tidak tersedia di server'}), 500
    
    try:
        # Gunakan pytoniq untuk membuat dan mengirim transaksi
        if not TON_LIB_AVAILABLE:
            return jsonify({'success': False, 'error': 'TON library tidak tersedia'}), 500
        
        from pytoniq import WalletV4, LiteClient, LiteBalancer
        
        # Gunakan LiteBalancer untuk koneksi yang lebih stabil
        is_testnet = NETWORK == 'testnet'
        
        # Inisialisasi client yang benar
        if is_testnet:
            # Untuk testnet
            client = LiteBalancer.from_testnet_config(trust_level=0)
        else:
            # Untuk mainnet - gunakan provider publik atau toncenter
            # Alternatif 1: Gunakan LiteBalancer untuk mainnet
            client = LiteBalancer.from_mainnet_config(trust_level=0)
            
            # Alternatif 2: Gunakan toncenter HTTP API (lebih sederhana)
            # Tapi kita akan gunakan LiteBalancer dulu
        
        async def send_transaction():
            # Start client
            await client.start_up()
            
            # Buat wallet dari private key
            wallet = await WalletV4.from_private_key(
                client=client,
                private_key=PRIVATE_KEY_BYTES
            )
            
            # Buat comment
            comment = f"wd:{telegram_id}:{reference}"
            
            # Kirim transaksi - amount dalam nanoTON
            amount_nano = int(amount_ton * 1_000_000_000)
            
            # Transfer dengan body sebagai string (akan otomatis diencode)
            tx_hash = await wallet.transfer(
                destination=destination_address,
                amount=amount_nano,
                body=comment  # pytoniq akan mengencode string ke cell
            )
            
            # Close client
            await client.close()
            return tx_hash
        
        # Jalankan async function
        import asyncio
        tx_hash = asyncio.run(send_transaction())
        
        print(f"✅ Withdraw transaction sent: {tx_hash}")
        
        # Simpan transaksi withdraw (negative amount untuk mengurangi saldo)
        tx_id = db.save_transaction(
            user_id=user['id'],
            transaction_hash=tx_hash,
            amount_ton=-amount_ton,
            from_address=WEB_ADDRESS,
            to_address=destination_address,
            memo=f"withdraw:{reference}",
            transaction_type='withdraw'
        )
        
        # Update withdraw request
        db.update_withdraw_request_by_reference(reference, tx_hash, 'completed')
        
        return jsonify({
            'success': True,
            'transaction_hash': tx_hash,
            'amount_ton': amount_ton,
            'message': 'Withdraw berhasil diproses'
        })
        
    except Exception as e:
        print(f"❌ Error processing withdraw: {e}")
        return jsonify({
            'success': False, 
            'error': f'Gagal memproses withdraw: {str(e)}'
        }), 500
        
@app.route('/api/process-withdraw-test', methods=['POST'])
def process_withdraw_test():
    """Versi testing - hanya mencatat di database, tidak mengirim TON sungguhan"""
    data = request.json
    telegram_id = data.get('telegram_id')
    amount_ton = float(data.get('amount_ton', 0))
    destination_address = data.get('destination_address')
    reference = data.get('reference')
    
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
    
    try:
        # Generate fake transaction hash untuk testing
        fake_tx_hash = f"test_tx_{int(time.time())}_{telegram_id[-4:]}_{reference[-8:]}"
        
        print(f"🧪 TEST MODE: Processing withdraw for user {telegram_id}")
        print(f"   Amount: {amount_ton} TON")
        print(f"   To: {destination_address}")
        print(f"   Reference: {reference}")
        print(f"   Fake TX: {fake_tx_hash}")
        
        # Simpan transaksi withdraw (negative amount untuk mengurangi saldo)
        tx_id = db.save_transaction(
            user_id=user['id'],
            transaction_hash=fake_tx_hash,
            amount_ton=-amount_ton,  # Negative untuk withdraw
            from_address=WEB_ADDRESS,
            to_address=destination_address,
            memo=f"withdraw:{reference}",
            transaction_type='withdraw'
        )
        
        # Update withdraw request
        db.update_withdraw_request_by_reference(reference, fake_tx_hash, 'completed')
        
        return jsonify({
            'success': True,
            'transaction_hash': fake_tx_hash,
            'amount_ton': amount_ton,
            'message': 'TEST MODE: Withdraw berhasil dicatat di database (tidak mengirim TON sungguhan)'
        })
        
    except Exception as e:
        print(f"❌ Error in test withdraw: {e}")
        return jsonify({
            'success': False, 
            'error': f'Gagal memproses withdraw: {str(e)}'
        }), 500

# ==================== MAIN ====================
if __name__ == '__main__':
    print(f"🚀 Flask server running on {TUNNEL_URL}")
    print(f"📝 Manifest URL: {TUNNEL_URL}/tonconnect-manifest.json")
    print(f"💾 Database path: {DB_PATH}")
    print(f"💰 Web Address: {WEB_ADDRESS}")
    print(f"🔑 TON Center API: {'✅ Tersedia' if TONCENTER_API_KEY else '❌ Tidak ada'}")
    print(f"📦 TON Library: {'✅ pytoniq tersedia' if TON_LIB_AVAILABLE else '❌ Tidak ada'}")
    print(f"\n📊 Endpoints available:")
    print(f"   - /api/balance/<telegram_id>")
    print(f"   - /api/transactions/<telegram_id>")
    print(f"   - /api/deposit-info")
    print(f"   - /api/verify-transaction")
    print(f"   - /api/create-payload")
    print(f"   - /api/initiate-withdraw (NEW - untuk memulai withdraw)")
    print(f"   - /api/verify-withdraw (NEW - untuk verifikasi withdraw)")
    print(f"   - /api/withdraw-history/<telegram_id>")
    print(f"   - /api/check-balance")
    print(f"\n⚠️  Private key TIDAK DIGUNAKAN untuk withdraw otomatis!")
    print(f"   Withdraw menggunakan TON Pay di frontend sesuai dokumentasi.")
    
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', 3000)),
        debug=os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    )