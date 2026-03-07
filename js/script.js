// ==================== KONFIGURASI ====================
const CONFIG = {
    TUNNEL_URL: 'https://sydney-recommendation-looked-perceived.trycloudflare.com',
    WEB_ADDRESS: '0QA9s4GFIMuO7qEF110duSQheIaGtr0T_HHjppW7cRiqiUqX',
    NETWORK: 'testnet',
    MIN_DEPOSIT: 0.1,
    DEBUG: true
};

// ==================== GLOBAL VARIABLES ====================
let tonConnectUI = null;
let telegramUser = null;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', async () => {
    debugLog('🚀 Application starting...');
    
    try {
        // Initialize components
        initTelegram();
        initTonConnect();
        updateNetworkBadge();
        
        // Check if TON Pay is available
        if (window.TonPay) {
            debugLog('✅ TON Pay SDK tersedia');
        } else {
            debugLog('⚠️ TON Pay SDK tidak tersedia - menggunakan metode manual');
        }
        
    } catch (error) {
        debugLog('❌ Initialization error:', error);
    }
});

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

// ==================== TON CONNECT FUNCTIONS ====================
function initTonConnect() {
    try {
        const manifestUrl = `${CONFIG.TUNNEL_URL}/tonconnect-manifest.json`;
        
        tonConnectUI = new TON_CONNECT_UI.TonConnectUI({
            manifestUrl: manifestUrl,
            buttonRootId: 'ton-connect',
            language: 'en',
            uiPreferences: {
                theme: 'SYSTEM',
                borderRadius: 'm'
            }
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

// ==================== DATABASE FUNCTIONS ====================
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

// ==================== DEPOSIT FUNCTIONS ====================
function showDepositModal() {
    const modal = document.getElementById('deposit-modal');
    if (!modal) return;
    
    // Reset modal state
    document.getElementById('deposit-form').classList.remove('hidden');
    document.getElementById('deposit-instructions').classList.add('hidden');
    document.getElementById('deposit-amount').value = '1.0';
    
    // Load deposit info
    document.getElementById('deposit-address').textContent = CONFIG.WEB_ADDRESS;
    
    modal.style.display = 'block';
}

function closeModal() {
    document.getElementById('deposit-modal').style.display = 'none';
}

/**
 * FUNGSI UTAMA: Proses deposit menggunakan metode manual
 * karena TON Pay SDK mungkin tidak tersedia
 */
async function processDeposit() {
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

        // Get sender address
        const senderAddress = tonConnectUI.account?.address;
        
        // Coba gunakan TON Pay jika tersedia
        if (window.TonPay) {
            await processDepositWithTonPay(amount, senderAddress);
        } else {
            await processDepositManual(amount, senderAddress);
        }

    } catch (error) {
        debugLog('❌ Payment failed:', error);
        
        if (error.message?.includes("rejected")) {
            showError('Transaction cancelled by user');
        } else {
            showError('Payment failed: ' + error.message);
        }
    } finally {
        const sendBtn = document.getElementById('send-deposit-btn');
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<span>💸</span> Send from Wallet';
    }
}

/**
 * Metode 1: Menggunakan TON Pay SDK (jika tersedia)
 */
async function processDepositWithTonPay(amount, senderAddress) {
    debugLog('📤 Menggunakan TON Pay SDK...');
    
    // Buat reference unik
    const timestamp = Date.now();
    const reference = `deposit_${telegramUser?.id}_${timestamp}`;
    const bodyHash = await sha256(reference);
    
    // Dapatkan payload dari backend atau buat manual
    const payloadResponse = await fetch(`${CONFIG.TUNNEL_URL}/api/create-payload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            telegram_id: telegramUser?.id.toString(),
            amount_ton: amount
        })
    });

    const payloadData = await payloadResponse.json();
    
    if (!payloadData.success) {
        throw new Error(payloadData.error || 'Failed to create payload');
    }

    // Simpan tracking data
    await fetch(`${CONFIG.TUNNEL_URL}/api/store-payment-tracking`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            reference,
            bodyBase64Hash: bodyHash,
            telegram_id: telegramUser?.id.toString(),
            amount
        })
    });

    // Kirim transaksi
    const transaction = {
        validUntil: Math.floor(Date.now() / 1000) + 600,
        messages: [payloadData.transaction]
    };

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

/**
 * Metode 2: Manual transaction (fallback jika TON Pay tidak tersedia)
 */
async function processDepositManual(amount, senderAddress) {
    debugLog('📤 Menggunakan metode manual...');
    
    // Buat transaction manual
    const amountNano = (amount * 1_000_000_000).toString();
    
    const transaction = {
        validUntil: Math.floor(Date.now() / 1000) + 600,
        messages: [
            {
                address: CONFIG.WEB_ADDRESS,
                amount: amountNano,
                // Optional: tambahkan comment
                payload: null // tanpa payload untuk simplicity
            }
        ]
    };

    debugLog('📤 Sending manual transaction:', transaction);

    // Kirim transaksi
    const result = await tonConnectUI.sendTransaction(transaction);
    debugLog('✅ Transaction sent:', result);

    // Buat reference sederhana
    const reference = `manual_${telegramUser?.id}_${Date.now()}`;

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

/**
 * Helper: SHA256 hash
 */
async function sha256(message) {
    const msgBuffer = new TextEncoder().encode(message);
    const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

function showTransactionSuccess(txHash, reference) {
    document.getElementById('deposit-form').classList.add('hidden');
    document.getElementById('deposit-instructions').classList.remove('hidden');
    document.getElementById('tx-hash').textContent = txHash.slice(0, 30) + '...';
    document.getElementById('tx-reference').textContent = reference;
    
    // Refresh data after 5 seconds
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
        logMessage += `\n${JSON.stringify(data, null, 2)}`;
    }
    
    if (debugElement) {
        debugElement.textContent = logMessage + '\n\n' + debugElement.textContent;
    }
    
    console.log(logMessage);
}

function toggleDebug() {
    const panel = document.getElementById('debug-panel');
    const content = document.getElementById('debug-info');
    const toggleIcon = document.querySelector('.toggle-icon');
    
    if (panel && content && toggleIcon) {
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
        badge.textContent = CONFIG.NETWORK === 'testnet' ? 'Testnet' : 'Mainnet';
        badge.className = `network-badge ${CONFIG.NETWORK}`;
    }
}

// Show debug panel
if (CONFIG.DEBUG) {
    document.getElementById('debug-panel')?.classList.remove('hidden');
}