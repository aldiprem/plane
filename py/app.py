@app.route('/api/process-withdraw', methods=['POST'])
def process_withdraw():
    """Versi REAL - mengirim TON menggunakan tonutils (sesuai standar TON)"""
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
        # Import dari tonutils
        from tonutils.client import ToncenterClient
        from tonutils.wallet import WalletV4R2
        from tonsdk.utils import to_nano
        
        print(f"📤 Memproses withdraw dengan tonutils...")
        
        # Inisialisasi client TON Center
        client = ToncenterClient(
            api_key=TONCENTER_API_KEY,
            is_testnet=(NETWORK == 'testnet')
        )
        
        # Buat wallet dari private key
        # Private key dalam format hex, tonutils akan handle konversi
        wallet = WalletV4R2.from_private_key(
            client=client,
            private_key=PRIVATE_KEY  # Langsung pakai string hex
        )
        
        # Buat comment
        comment = f"wd:{telegram_id}:{reference}"
        
        # Kirim transaksi
        # to_nano mengkonversi TON ke nanoTON
        tx_hash = wallet.transfer(
            destination=destination_address,
            amount=to_nano(amount_ton, 'ton'),
            body=comment,
            send_mode=3  # Mode default untuk transfer
        )
        
        print(f"✅ Transaksi berhasil dikirim: {tx_hash}")
        
        # Simpan transaksi withdraw (negative amount)
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
        
        # Update payment tracking
        db.update_payment_tracking_status(reference, 'completed', tx_hash)
        
        return jsonify({
            'success': True,
            'transaction_hash': tx_hash,
            'amount_ton': amount_ton,
            'message': 'Withdraw berhasil dikirim ke blockchain!'
        })
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return jsonify({
            'success': False,
            'error': 'Library TON tidak lengkap. Jalankan: pip install tonutils aiofiles'
        }), 500
        
    except Exception as e:
        print(f"❌ Error in withdraw: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False, 
            'error': f'Gagal memproses withdraw: {str(e)}'
        }), 500