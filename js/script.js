// ==================== KONFIGURASI ====================
const TUNNEL_URL = 'https://sydney-recommendation-looked-perceived.trycloudflare.com';
const MANIFEST_URL = `${TUNNEL_URL}/tonconnect-manifest.json`;

const WEB_ADDRESS = '0QA9s4GFIMuO7qEF110duSQheIaGtr0T_HHjppW7cRiqiUqX';

const { createTonPayTransfer, TON } = window.TonPay;

// Global variables
let tonConnectUI = null;
let telegramUser = null;

// ==================== UTILITY FUNCTIONS ====================
function debugLog(message, data = null) {
    const debugElement = document.getElementById('debug-info');
    const timestamp = new Date().toISOString();
    let logMessage = `[${timestamp}] ${message}`;
    if (data) {
        logMessage += `\n${JSON.stringify(data, null, 2)}`;
    }
    if (debugElement) {
        debugElement.textContent = logMessage;
    }
    console.log(logMessage);
}

function formatAddress(address) {
    if (!address) return 'Not connected';
    const start = address.slice(0, 6);
    const end = address.slice(-4);
    return `${start}...${end}`;
}

// ==================== TELEGRAM FUNCTIONS ====================
function initTelegram() {
    try {
        if (window.Telegram && window.Telegram.WebApp) {
            const tg = window.Telegram.WebApp;
            tg.ready();
            tg.expand();

            telegramUser = tg.initDataUnsafe?.user;

            if (telegramUser) {
                displayTelegramData(telegramUser);
                saveUserToDatabase(telegramUser);
                loadUserBalance();
                loadTransactionHistory();
                debugLog('Telegram user data loaded', telegramUser);
            } else {
                document.getElementById('telegram-data').innerHTML = `
                    <p class="error">⚠️ Buka di dalam Telegram Web App untuk melihat data user</p>
                `;
                debugLog('No Telegram user data available');
            }
        } else {
            document.getElementById('telegram-data').innerHTML = `
                <p class="error">⚠️ Telegram Web App tidak tersedia</p>
            `;
            debugLog('Telegram Web App not available');
        }
    } catch (error) {
        debugLog('Error initializing Telegram', error);
    }
}

function displayTelegramData(user) {
    const container = document.getElementById('telegram-data');
    if (!container) return;

    let photoUrl = user.photo_url || `https://ui-avatars.com/api/?name=${user.first_name}+${user.last_name || ''}&size=200&background=667eea&color=fff&bold=true`;

    container.innerHTML = `
        <div class="user-info">
            <img src="${photoUrl}" alt="Profile" class="user-avatar" onerror="this.src='https://ui-avatars.com/api/?name=${user.first_name}+${user.last_name || ''}&size=200&background=667eea&color=fff&bold=true'">
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
        const response = await fetch(`${TUNNEL_URL}/api/user`, {
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
        debugLog('User saved to database', data);
    } catch (error) {
        debugLog('Error saving user to database', error);
    }
}

// ==================== TON CONNECT FUNCTIONS ====================
function initTonConnect() {
    try {
        tonConnectUI = new TON_CONNECT_UI.TonConnectUI({
            manifestUrl: MANIFEST_URL,
            buttonRootId: 'ton-connect',
            language: 'en',
            uiPreferences: {
                theme: 'SYSTEM',
                borderRadius: 'm'
            }
        });

        debugLog('TON Connect initialized', { manifestUrl: MANIFEST_URL });

        tonConnectUI.onStatusChange(async (wallet) => {
            debugLog('Wallet status changed', wallet);

            if (wallet && telegramUser) {
                displayWalletInfo(wallet);
                await updateUserWallet(telegramUser.id, wallet.account.address);
            } else {
                document.getElementById('wallet-info')?.classList.add('hidden');
            }
        });

    } catch (error) {
        debugLog('Error initializing TON Connect', error);
    }
}

function displayWalletInfo(wallet) {
    const walletInfo = document.getElementById('wallet-info');
    const walletAddress = document.getElementById('wallet-address');
    
    if (!walletInfo || !walletAddress) return;

    walletAddress.setAttribute('data-full-address', wallet.account.address);
    walletAddress.innerHTML = `
        <span class="address-full hidden">${wallet.account.address}</span>
        <span class="address-short">${formatAddress(wallet.account.address)}</span>
        <button class="copy-btn" onclick="copyAddress()" title="Copy full address">📋</button>
    `;

    loadWalletBalance(wallet.account.address);
    walletInfo.classList.remove('hidden');
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
        debugLog('Error loading balance', error);
    }
}

window.copyAddress = function() {
    const fullAddress = document.querySelector('[data-full-address]')?.getAttribute('data-full-address');
    if (fullAddress) {
        navigator.clipboard.writeText(fullAddress);
        alert('Address copied!');
    }
}

async function updateUserWallet(telegramId, walletAddress) {
    try {
        const response = await fetch(`${TUNNEL_URL}/api/user/wallet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                telegram_id: telegramId.toString(),
                wallet_address: walletAddress
            })
        });

        const data = await response.json();
        debugLog('Wallet address updated in database', data);
    } catch (error) {
        debugLog('Error updating wallet address', error);
    }
}

// ==================== DEPOSIT MODAL FUNCTIONS ====================
function showDepositModal() {
    const oldModal = document.getElementById('deposit-modal');
    if (oldModal) oldModal.remove();

    const modal = document.createElement('div');
    modal.id = 'deposit-modal';
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <span class="close">&times;</span>
            <h3>💎 Deposit TON</h3>
            <div id="deposit-status"></div>
            <div class="deposit-form">
                <label>Amount (TON):</label>
                <input type="number" id="deposit-amount" min="0.1" step="0.1" value="1.0">
                
                <div class="deposit-address-section">
                    <p><strong>Send to address:</strong></p>
                    <div class="address-box">
                        <code id="deposit-address">Loading...</code>
                        <button onclick="copyDepositAddress()">📋 Copy</button>
                    </div>
                </div>

                <div class="deposit-memo-section">
                    <p><strong>Memo (auto-generated):</strong></p>
                    <div class="memo-box">
                        <code id="deposit-memo">Loading...</code>
                        <button onclick="copyDepositMemo()">📋 Copy</button>
                    </div>
                    <small>Memo akan otomatis dibuat saat transaksi</small>
                </div>

                <button id="send-deposit-btn" class="btn-primary" onclick="processDeposit()">
                    Send from Wallet
                </button>
            </div>
            <div id="deposit-instructions" class="hidden">
                <p>✅ Transaction sent! Waiting for confirmation...</p>
                <p>Transaction hash: <code id="tx-hash"></code></p>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    modal.style.display = 'block';
    modal.querySelector('.close').onclick = () => modal.remove();
    loadDepositInfo();
}

async function loadDepositInfo() {
    try {
        document.getElementById('deposit-address').textContent = WEB_ADDRESS;
        document.getElementById('deposit-memo').textContent = "Auto-generated saat transaksi";
    } catch (error) {
        debugLog('Error loading deposit info', error);
    }
}

async function processDeposit() {
  if (!tonConnectUI || !tonConnectUI.connected) {
    await tonConnectUI.connect();
    return;
  }

  const amount = parseFloat(document.getElementById('deposit-amount').value);

  if (amount < 0.1) {
    alert('Minimum deposit is 0.1 TON');
    return;
  }

  try {
    const sendBtn = document.getElementById('send-deposit-btn');
    sendBtn.disabled = true;
    sendBtn.textContent = 'Processing...';

    // 1. Dapatkan sender address dari wallet yang terhubung
    const senderAddress = tonConnectUI.account?.address;
    
    // 2. Panggil createTonPayTransfer (sesuai dokumentasi)
    const { message, reference, bodyBase64Hash } = await createTonPayTransfer(
      {
        amount: amount,
        asset: "TON",
        recipientAddr: WEB_ADDRESS,
        senderAddr: senderAddress,
        commentToSender: "Deposit ke Marketplace",
        commentToRecipient: `Deposit dari user ${telegramUser.id}`,
      },
      {
        chain: "testnet",
      }
    );

    console.log('📤 TON Pay transaction created:', { message, reference, bodyBase64Hash });

    // 3. Simpan tracking data ke server
    await fetch(`${TUNNEL_URL}/api/store-payment-tracking`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference,
        bodyBase64Hash,
        telegram_id: telegramUser.id.toString(),
        amount
      })
    });

    // 4. Kirim transaksi menggunakan TON Connect
    const transaction = {
      validUntil: Math.floor(Date.now() / 1000) + 600, // 10 menit
      messages: [message] // Langsung gunakan message dari createTonPayTransfer
    };

    const result = await tonConnectUI.sendTransaction(transaction);
    console.log('✅ Transaction result:', result);

    // 5. Record di database
    await fetch(`${TUNNEL_URL}/api/verify-transaction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        telegram_id: telegramUser.id.toString(),
        transaction_hash: result.boc,
        amount_ton: amount,
        from_address: senderAddress,
        reference: reference // Simpan reference untuk tracking nanti
      })
    });

    // 6. Tampilkan sukses
    document.querySelector('.deposit-form')?.classList.add('hidden');
    document.getElementById('deposit-instructions')?.classList.remove('hidden');
    document.getElementById('tx-hash').textContent = result.boc;
    document.getElementById('tx-reference').textContent = reference;

    debugLog('✅ Deposit transaction sent successfully', { result, reference });

  } catch (error) {
    console.error('❌ Payment failed:', error);

    if (error.message?.includes("rejected")) {
      alert('Transaction cancelled by user.');
    } else {
      alert('Payment failed: ' + error.message);
    }
  } finally {
    const sendBtn = document.getElementById('send-deposit-btn');
    if (sendBtn) {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send from Wallet';
    }
  }
}

// ==================== COPY FUNCTIONS ====================
window.copyDepositAddress = function() {
    const address = document.getElementById('deposit-address')?.textContent;
    if (address && address !== 'Loading...') {
        navigator.clipboard.writeText(address);
        alert('Address copied!');
    }
};

window.copyDepositMemo = function() {
    const memo = document.getElementById('deposit-memo')?.textContent;
    if (memo && memo !== 'Loading...') {
        navigator.clipboard.writeText(memo);
        alert('Memo copied!');
    }
};

// ==================== TRANSACTION HISTORY FUNCTIONS ====================
async function loadTransactionHistory() {
    if (!telegramUser) return;

    try {
        const response = await fetch(`${TUNNEL_URL}/api/transactions/${telegramUser.id}?limit=10`);
        const data = await response.json();
        if (data.success && data.transactions.length > 0) {
            displayTransactions(data.transactions);
        } else {
            document.getElementById('transactions-list').innerHTML = '<p>No transactions yet</p>';
        }
    } catch (error) {
        debugLog('Error loading transactions', error);
    }
}

function displayTransactions(transactions) {
    const container = document.getElementById('transactions-list');
    if (!container) return;

    let html = '<h3>Recent Transactions</h3><ul class="transactions">';
    transactions.forEach(tx => {
        const date = new Date(tx.created_at).toLocaleDateString();
        const statusClass = tx.status === 'confirmed' ? 'confirmed' : 'pending';
        html += `
            <li class="transaction-item ${statusClass}">
                <span class="tx-date">${date}</span>
                <span class="tx-amount">${tx.amount_ton} TON</span>
                <span class="tx-status ${tx.status}">${tx.status}</span>
                <span class="tx-type">${tx.transaction_type}</span>
            </li>
        `;
    });
    html += '</ul>';
    container.innerHTML = html;
}

// ==================== BALANCE FUNCTIONS ====================
async function loadUserBalance() {
    if (!telegramUser) return;

    try {
        const response = await fetch(`${TUNNEL_URL}/api/balance/${telegramUser.id}`);
        const data = await response.json();
        if (data.success) {
            const balanceElement = document.getElementById('user-balance');
            if (balanceElement) {
                balanceElement.textContent = data.formatted;
            }
        }
    } catch (error) {
        debugLog('Error loading user balance', error);
    }
}

// ==================== TEST FUNCTIONS (OPTIONAL) ====================
async function sendMinimalTransaction() {
    if (!tonConnectUI || !tonConnectUI.connected) {
        await tonConnectUI.connect();
        return;
    }

    try {
        const transaction = {
            validUntil: Math.floor(Date.now() / 1000) + 600,
            messages: [
                {
                    address: WEB_ADDRESS,
                    amount: "100000000" // 0.1 TON
                }
            ]
        };

        const result = await tonConnectUI.sendTransaction(transaction);
        console.log('Test transaction success:', result);
        alert('Test transaction sent! Check console.');
    } catch (error) {
        console.error('Test transaction failed:', error);
        alert('Test failed: ' + error.message);
    }
}

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    debugLog('Page loaded, initializing...');
    initTelegram();
    initTonConnect();
});
