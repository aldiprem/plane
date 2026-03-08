// ==================== KONFIGURASI ====================
const CONFIG = {
    // Ganti dengan URL tunnel Anda
    TUNNEL_URL: 'https://sydney-recommendation-looked-perceived.trycloudflare.com',
    WEB_ADDRESS: 'UQBX9MJCyRK3-eQjh7CgbwB2bR9hT5vYAdzx4uv_CagAo4Ra',
    NETWORK: 'mainnet',
    MIN_DEPOSIT: 0.1,
    DEBUG: true
};

// ==================== GLOBAL VARIABLES ====================
let tonConnectUI = null;
let telegramUser = null;
let tonPay = null;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', async () => {
    debugLog('🚀 Application starting...');
    
    try {
        // Check if TON Pay is available
        if (window.TonPay) {
            tonPay = window.TonPay;
            debugLog('✅ TON Pay SDK tersedia', { 
                functions: Object.keys(tonPay) 
            });
        } else {
            debugLog('❌ TON Pay SDK TIDAK tersedia - pastikan script di-load dengan benar');
        }

        // Initialize components
        initTelegram();
        initTonConnect();
        updateNetworkBadge();
        
    } catch (error) {
        debugLog('❌ Initialization error:', error);
    }
});

// ==================== WITHDRAW FUNCTIONS ====================

async function processWithdraw() {
  // Validasi koneksi wallet user (untuk menerima dana)
  if (!tonConnectUI?.connected) {
    showWithdrawStatus('⚠️ Please connect your wallet first to receive funds', 'warning');
    await tonConnectUI.connect();
    return;
  }

  if (!telegramUser) {
    showWithdrawStatus('⚠️ Please open in Telegram Web App', 'warning');
    return;
  }

  const amount = parseFloat(document.getElementById('withdraw-amount').value);
  const maxWithdraw = parseFloat(document.getElementById('max-withdraw').textContent);

  if (isNaN(amount) || amount < 0.1) {
    showWithdrawStatus('❌ Minimum withdraw is 0.1 TON', 'error');
    return;
  }

  if (amount > maxWithdraw) {
    showWithdrawStatus(`❌ Maximum withdraw is ${maxWithdraw} TON`, 'error');
    return;
  }

  // Konfirmasi user
  if (!confirm(`Are you sure you want to withdraw ${amount} TON?\n\nThis will be sent to your wallet:\n${formatAddress(tonConnectUI.account?.address)}`)) {
    return;
  }

  const withdrawBtn = document.getElementById('withdraw-btn');
  const originalText = withdrawBtn.innerHTML;
  withdrawBtn.disabled = true;
  withdrawBtn.innerHTML = '<span>⏳</span> Processing Withdrawal...';

  try {
    const destinationAddress = tonConnectUI.account?.address;

    debugLog('📤 Processing withdrawal:', { amount, destination: destinationAddress });

    // 1. Initiate withdraw di backend
    const initResponse = await fetch(`${CONFIG.TUNNEL_URL}/api/initiate-withdraw`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        telegram_id: telegramUser.id.toString(),
        amount_ton: amount,
        destination_address: destinationAddress
      })
    });

    const initData = await initResponse.json();
    if (!initData.success) {
      throw new Error(initData.error || 'Failed to initiate withdraw');
    }

    debugLog('✅ Withdraw initiated:', initData);

    // 2. GUNAKAN ENDPOINT TEST (tidak mengirim TON sungguhan)
    showWithdrawStatus('⏳ Processing withdrawal (TEST MODE)...', 'info');

    const processResponse = await fetch(`${CONFIG.TUNNEL_URL}/api/process-withdraw`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        telegram_id: telegramUser.id.toString(),
        amount_ton: amount,
        destination_address: destinationAddress,
        reference: initData.reference
      })
    });

    const processData = await processResponse.json();

    if (!processData.success) {
      throw new Error(processData.error || 'Failed to process withdraw');
    }

    debugLog('✅ Withdraw processed by server (TEST MODE):', processData);

    // 3. Tampilkan sukses
    showWithdrawStatus(
      `✅ TEST MODE: Withdrawal recorded! ${amount} TON deducted from your balance.\nTransaction: ${processData.transaction_hash}`,
      'success'
    );

    // Reset form
    document.getElementById('withdraw-amount').value = '1.0';

    // Refresh data
    setTimeout(() => {
      loadUserBalance();
      loadTransactionHistory();
    }, 3000);

  } catch (error) {
    debugLog('❌ Withdraw error:', error);

    let errorMessage = error.message;
    if (error.message.includes('rejected')) {
      errorMessage = 'Transaction cancelled';
    } else if (error.message.includes('Insufficient balance')) {
      errorMessage = 'Insufficient balance in merchant wallet';
    }

    showWithdrawStatus(`❌ ${errorMessage}`, 'error');
  } finally {
    withdrawBtn.disabled = false;
    withdrawBtn.innerHTML = originalText;
  }
}

function base64EncodeComment(comment) {
  try {
    // Batasi panjang comment
    if (comment.length > 120) {
      comment = comment.substring(0, 120);
    }

    const encoder = new TextEncoder();
    const commentBytes = encoder.encode(comment);

    // Prefix untuk text comment (4 byte 0) - format standar TON
    const prefix = new Uint8Array([0, 0, 0, 0]);
    const fullBytes = new Uint8Array(prefix.length + commentBytes.length);
    fullBytes.set(prefix);
    fullBytes.set(commentBytes, prefix.length);

    // Konversi ke Base64
    let binary = '';
    for (let i = 0; i < fullBytes.length; i++) {
      binary += String.fromCharCode(fullBytes[i]);
    }
    return btoa(binary);
  } catch (e) {
    debugLog('Error encoding comment:', e);
    return undefined; // Kirim tanpa payload jika error
  }
}

function showWithdrawStatus(message, type = 'info') {
  const statusEl = document.getElementById('withdraw-status');
  if (statusEl) {
    statusEl.className = `status-message ${type}`;
    statusEl.textContent = message;
    statusEl.classList.remove('hidden');

    if (type === 'success' || type === 'error') {
      setTimeout(() => {
        statusEl.classList.add('hidden');
      }, 5000);
    }
  }
}

function updateMaxWithdraw() {
  const balanceElement = document.getElementById('user-balance');
  const maxWithdrawElement = document.getElementById('max-withdraw');
  const withdrawAmount = document.getElementById('withdraw-amount');
  const withdrawBtn = document.getElementById('withdraw-btn');
  const withdrawWarning = document.getElementById('withdraw-warning');

  if (balanceElement && maxWithdrawElement) {
    const balance = parseFloat(balanceElement.textContent) || 0;
    maxWithdrawElement.textContent = balance.toFixed(2);

    if (tonConnectUI?.connected) {
      withdrawWarning.classList.add('hidden');
      withdrawBtn.disabled = false;

      if (withdrawAmount) {
        const amount = parseFloat(withdrawAmount.value) || 0;
        withdrawAmount.style.borderColor = amount > balance ? 'var(--danger-color)' : '';
      }
    } else {
      withdrawWarning.classList.remove('hidden');
      withdrawBtn.disabled = true;
    }
  }
}

// ==================== WITHDRAW HISTORY ====================
async function loadWithdrawHistory() {
  if (!telegramUser) return;

  try {
    const response = await fetch(`${CONFIG.TUNNEL_URL}/api/withdraw-history/${telegramUser.id}`);
    const data = await response.json();

    if (data.success) {
      displayWithdrawHistory(data.requests);
    }
  } catch (error) {
    debugLog('❌ Error loading withdraw history:', error);
  }
}

function displayWithdrawHistory(requests) {
  const container = document.getElementById('withdraw-history');
  if (!container) return;

  if (!requests?.length) {
    container.innerHTML = '<div class="loading-spinner">No withdraw requests yet</div>';
    return;
  }

  let html = '<ul class="transactions-list">';
  requests.forEach(req => {
    const date = new Date(req.created_at).toLocaleDateString('id-ID', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    });

    html += `
            <li class="transaction-item confirmed">
                <div>
                    <div class="tx-date">${date}</div>
                    <div class="tx-amount">-${req.amount_ton} TON</div>
                    <small class="tx-address">To: ${formatAddress(req.destination_address)}</small>
                </div>
                <div class="tx-status confirmed">Completed</div>
            </li>
        `;
  });
  html += '</ul>';

  container.innerHTML = html;
}

// ==================== TELEGRAM FUNCTIONS ====================
function initTelegram() {
    try {
        if (!window.Telegram?.WebApp) {
            throw new Error('Telegram Web App not available');
        }

        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();

        telegramUser = tg.initDataUnsafe?.user;
        
        if (telegramUser) {
            updateTelegramStatus('connected');
            displayTelegramProfile(telegramUser);
            saveUserToDatabase(telegramUser);
            loadUserBalance();
            loadTransactionHistory();
            debugLog('✅ Telegram user loaded:', telegramUser);
        } else {
            updateTelegramStatus('disconnected');
            document.getElementById('telegram-profile').innerHTML = `
                <div class="error-message">
                    ⚠️ Please open in Telegram Web App
                </div>
            `;
        }
    } catch (error) {
        debugLog('❌ Telegram init error:', error);
        updateTelegramStatus('disconnected');
    }
}

function updateTelegramStatus(status) {
    const badge = document.getElementById('telegram-status');
    if (!badge) return;
    
    badge.className = 'status-badge ' + status;
    badge.textContent = status === 'connected' ? 'Connected' : 'Disconnected';
}

function displayTelegramProfile(user) {
    const container = document.getElementById('telegram-profile');
    if (!container) return;

    const photoUrl = user.photo_url || `https://ui-avatars.com/api/?name=${user.first_name}+${user.last_name || ''}&size=200&background=667eea&color=fff&bold=true`;

    container.innerHTML = `
        <div class="user-info">
            <img src="${photoUrl}" 
                 alt="Profile" 
                 class="user-avatar"
                 onerror="this.src='https://ui-avatars.com/api/?name=${user.first_name}+${user.last_name || ''}&size=200&background=667eea&color=fff&bold=true'">
            <div class="user-details">
                <p><strong>Name:</strong> ${user.first_name} ${user.last_name || ''}</p>
                <p><strong>Username:</strong> ${user.username ? '@' + user.username : '-'}</p>
                <p><strong>User ID:</strong> ${user.id}</p>
                <p><strong>Language:</strong> ${user.language_code || 'en'}</p>
            </div>
        </div>
    `;
}

async function saveUserToDatabase(user) {
    try {
        const response = await fetch(`${CONFIG.TUNNEL_URL}/api/user`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                telegram_id: user.id.toString(),
                telegram_username: user.username,
                telegram_first_name: user.first_name,
                telegram_last_name: user.last_name,
                telegram_photo_url: user.photo_url
            })
        });

        const data = await response.json();
        debugLog('✅ User saved to database:', data);
    } catch (error) {
        debugLog('❌ Error saving user:', error);
    }
}

// ==================== TON CONNECT FUNCTIONS ====================
function initTonConnect() {
    try {
        const manifestUrl = `${CONFIG.TUNNEL_URL}/tonconnect-manifest.json`;
        
        tonConnectUI = new TON_CONNECT_UI.TonConnectUI({
            manifestUrl: manifestUrl,
            buttonRootId: 'ton-connect',
            language: 'en'
        });

        debugLog('✅ TON Connect initialized');

        tonConnectUI.onStatusChange(async (wallet) => {
            debugLog('📱 Wallet status changed:', wallet);
            
            if (wallet && telegramUser) {
                updateWalletStatus('connected');
                displayWalletInfo(wallet);
                await updateUserWallet(telegramUser.id, wallet.account.address);
            } else {
                updateWalletStatus('disconnected');
                document.getElementById('wallet-info')?.classList.add('hidden');
            }
        });

    } catch (error) {
        debugLog('❌ TON Connect init error:', error);
        updateWalletStatus('disconnected');
    }
}

function updateWalletStatus(status) {
    const badge = document.getElementById('wallet-status');
    if (!badge) return;
    
    badge.className = 'status-badge ' + status;
    badge.textContent = status === 'connected' ? 'Connected' : 'Disconnected';
}

function displayWalletInfo(wallet) {
    const walletInfo = document.getElementById('wallet-info');
    const walletAddress = document.getElementById('wallet-address');
    
    if (!walletInfo || !walletAddress) return;

    const address = wallet.account.address;
    
    walletAddress.setAttribute('data-full-address', address);
    walletAddress.textContent = formatAddress(address);
    walletInfo.classList.remove('hidden');
    
    loadWalletBalance(address);
}

function formatAddress(address) {
    if (!address) return 'Not connected';
    if (address.length < 10) return address;
    return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

async function loadWalletBalance(address) {
    try {
        const response = await fetch(`https://toncenter.com/api/v2/getAddressBalance?address=${address}`);
        const data = await response.json();
        
        if (data.ok) {
            const balanceNano = parseInt(data.result);
            const balanceTon = balanceNano / 1_000_000_000;
            document.getElementById('wallet-balance').textContent = `${balanceTon.toFixed(2)} TON`;
        }
    } catch (error) {
        debugLog('❌ Error loading wallet balance:', error);
    }
}

async function updateUserWallet(telegramId, walletAddress) {
    try {
        const response = await fetch(`${CONFIG.TUNNEL_URL}/api/user/wallet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                telegram_id: telegramId.toString(),
                wallet_address: walletAddress
            })
        });

        const data = await response.json();
        debugLog('✅ Wallet updated:', data);
    } catch (error) {
        debugLog('❌ Error updating wallet:', error);
    }
}

// ==================== DEPOSIT FUNCTIONS - SESUAI DOKUMENTASI ====================
function showDepositModal() {
    const modal = document.getElementById('deposit-modal');
    if (!modal) return;
    
    document.getElementById('deposit-form').classList.remove('hidden');
    document.getElementById('deposit-instructions').classList.add('hidden');
    document.getElementById('deposit-amount').value = '1.0';
    
    modal.style.display = 'block';
}

function closeModal() {
    document.getElementById('deposit-modal').style.display = 'none';
}

async function processDeposit() {
  // Validasi koneksi wallet
  if (!tonConnectUI?.connected) {
    await tonConnectUI.connect();
    return;
  }

  const amount = parseFloat(document.getElementById('deposit-amount').value);

  if (amount < CONFIG.MIN_DEPOSIT) {
    showError(`Minimum deposit is ${CONFIG.MIN_DEPOSIT} TON`);
    return;
  }

  try {
    const sendBtn = document.getElementById('send-deposit-btn');
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span>⏳</span> Processing...';

    const senderAddress = tonConnectUI.account?.address;

    debugLog('📤 Processing deposit:', { amount, senderAddress });

    // Buat memo
    const memo = `deposit:${telegramUser?.id}:${Date.now()}`;

    // Konversi ke nanoTON (1 TON = 1,000,000,000 nanoTON)
    // Pastikan dalam bentuk string dan tidak ada floating point error
    const amountNano = Math.floor(amount * 1_000_000_000).toString();

    debugLog('💰 Amount in nanoTON:', amountNano);

    // Buat transaction manual
    const transaction = {
      validUntil: Math.floor(Date.now() / 1000) + 600, // 10 menit
      messages: [
        {
          address: CONFIG.WEB_ADDRESS,
          amount: amountNano, // String, dalam nanoTON
          // Optional: tambahkan comment dengan format yang benar
          payload: base64EncodeComment(memo)
                }
            ]
    };

    debugLog('📤 Sending transaction:', JSON.stringify(transaction, null, 2));

    // Kirim transaksi
    const result = await tonConnectUI.sendTransaction(transaction);
    debugLog('✅ Transaction sent:', result);

    // Record transaction di database
    const verifyResponse = await fetch(`${CONFIG.TUNNEL_URL}/api/verify-transaction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        telegram_id: telegramUser?.id.toString(),
        transaction_hash: result.boc,
        amount_ton: amount,
        from_address: senderAddress,
        memo: memo
      })
    });

    const verifyData = await verifyResponse.json();
    debugLog('✅ Transaction verified:', verifyData);

    // Tampilkan sukses
    showTransactionSuccess(result.boc, `deposit_${Date.now()}`);

  } catch (error) {
    debugLog('❌ Payment failed:', {
      message: error.message,
      name: error.name
    });

    if (error.message?.includes("rejected")) {
      showError('Transaction cancelled by user');
    } else {
      showError('Payment failed: ' + error.message);
    }
  } finally {
    const sendBtn = document.getElementById('send-deposit-btn');
    if (sendBtn) {
      sendBtn.disabled = false;
      sendBtn.innerHTML = '<span>💸</span> Send from Wallet';
    }
  }
}

/**
 * FALLBACK: Metode manual jika TON Pay tidak tersedia
 */
async function processDepositManual(amount, senderAddress) {
    debugLog('📤 Menggunakan metode manual...');
    
    // Buat reference unik
    const reference = `manual_${telegramUser?.id}_${Date.now()}`;
    
    // Buat transaction manual
    const amountNano = (amount * 1_000_000_000).toString();
    
    const transaction = {
        validUntil: Math.floor(Date.now() / 1000) + 600,
        messages: [
            {
                address: CONFIG.WEB_ADDRESS,
                amount: amountNano
            }
        ]
    };

    debugLog('📤 Sending manual transaction:', transaction);

    const result = await tonConnectUI.sendTransaction(transaction);
    debugLog('✅ Transaction sent:', result);

    // Record transaction
    await fetch(`${CONFIG.TUNNEL_URL}/api/verify-transaction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            telegram_id: telegramUser?.id.toString(),
            transaction_hash: result.boc,
            amount_ton: amount,
            from_address: senderAddress,
            reference: reference
        })
    });

    showTransactionSuccess(result.boc, reference);
}

function showTransactionSuccess(txHash, reference) {
    document.getElementById('deposit-form').classList.add('hidden');
    document.getElementById('deposit-instructions').classList.remove('hidden');
    document.getElementById('tx-hash').textContent = txHash.slice(0, 30) + '...';
    document.getElementById('tx-reference').textContent = reference;
    
    // Refresh data setelah 5 detik
    setTimeout(() => {
        loadUserBalance();
        loadTransactionHistory();
    }, 5000);
}

// ==================== BALANCE FUNCTIONS ====================
async function loadUserBalance() {
    if (!telegramUser) return;

    try {
        const response = await fetch(`${CONFIG.TUNNEL_URL}/api/balance/${telegramUser.id}`);
        const data = await response.json();
        
        if (data.success) {
            const balanceElement = document.getElementById('user-balance');
            if (balanceElement) {
                balanceElement.textContent = data.formatted;
            }
        }
    } catch (error) {
        debugLog('❌ Error loading balance:', error);
    }
}

function refreshBalance() {
    loadUserBalance();
    if (tonConnectUI?.account) {
        loadWalletBalance(tonConnectUI.account.address);
    }
}

// ==================== TRANSACTION FUNCTIONS ====================
async function loadTransactionHistory() {
    if (!telegramUser) return;

    try {
        const response = await fetch(`${CONFIG.TUNNEL_URL}/api/transactions/${telegramUser.id}?limit=10`);
        const data = await response.json();
        
        if (data.success) {
            displayTransactions(data.transactions);
        }
    } catch (error) {
        debugLog('❌ Error loading transactions:', error);
    }
}

function refreshTransactions() {
    loadTransactionHistory();
}

function displayTransactions(transactions) {
    const container = document.getElementById('transactions-list');
    if (!container) return;

    if (!transactions?.length) {
        container.innerHTML = '<div class="loading-spinner">No transactions yet</div>';
        return;
    }

    let html = '<ul class="transactions-list">';
    transactions.forEach(tx => {
        const date = new Date(tx.created_at).toLocaleDateString('id-ID', {
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit'
        });
        
        html += `
            <li class="transaction-item ${tx.status}">
                <div>
                    <div class="tx-date">${date}</div>
                    <div class="tx-amount">${tx.amount_ton} TON</div>
                </div>
                <div class="tx-status ${tx.status}">${tx.status}</div>
            </li>
        `;
    });
    html += '</ul>';
    
    container.innerHTML = html;
}

// ==================== COPY FUNCTIONS ====================
window.copyAddress = function() {
    const fullAddress = document.querySelector('[data-full-address]')?.getAttribute('data-full-address');
    if (fullAddress) {
        navigator.clipboard.writeText(fullAddress);
        showToast('Address copied!');
    }
};

window.copyDepositAddress = function() {
    const address = document.getElementById('deposit-address')?.textContent;
    if (address && address !== 'Loading...') {
        navigator.clipboard.writeText(address);
        showToast('Address copied!');
    }
};

function copyTxHash() {
    const txHash = document.getElementById('tx-hash')?.textContent;
    if (txHash) {
        navigator.clipboard.writeText(txHash);
        showToast('Transaction hash copied!');
    }
}

function copyReference() {
    const reference = document.getElementById('tx-reference')?.textContent;
    if (reference) {
        navigator.clipboard.writeText(reference);
        showToast('Reference copied!');
    }
}

// ==================== UTILITY FUNCTIONS ====================
function debugLog(message, data = null) {
    if (!CONFIG.DEBUG) return;
    
    const debugElement = document.getElementById('debug-info');
    const timestamp = new Date().toISOString();
    let logMessage = `[${timestamp}] ${message}`;
    
    if (data) {
        try {
            logMessage += `\n${JSON.stringify(data, null, 2)}`;
        } catch (e) {
            logMessage += `\n[Unstringifiable Data]`;
        }
    }
    
    if (debugElement) {
        debugElement.textContent = logMessage + '\n\n' + debugElement.textContent;
    }
    
    console.log(logMessage, data || '');
}

function toggleDebug() {
    const content = document.getElementById('debug-info');
    const toggleIcon = document.querySelector('.toggle-icon');
    
    if (content && toggleIcon) {
        content.classList.toggle('hidden');
        toggleIcon.textContent = content.classList.contains('hidden') ? '▶' : '▼';
    }
}

function showError(message) {
    const statusEl = document.getElementById('deposit-status');
    if (statusEl) {
        statusEl.className = 'status-message error';
        statusEl.textContent = message;
        statusEl.classList.remove('hidden');
        
        setTimeout(() => {
            statusEl.classList.add('hidden');
        }, 5000);
    }
    alert(message);
}

function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'status-message success';
    toast.textContent = message;
    toast.style.position = 'fixed';
    toast.style.bottom = '20px';
    toast.style.left = '50%';
    toast.style.transform = 'translateX(-50%)';
    toast.style.zIndex = '2000';
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 2000);
}

function updateNetworkBadge() {
    const badge = document.querySelector('.network-badge');
    if (badge) {
        badge.textContent = CONFIG.NETWORK === 'mainnet' ? 'Testnet' : 'Mainnet';
        badge.className = `network-badge ${CONFIG.NETWORK}`;
    }
}