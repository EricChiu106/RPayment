import os                          
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, Response
import requests
from datetime import datetime,  timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_session import Session # 伺服器端執行: pip install flask-session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import time
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 提升到 16MB

# 讓 Flask 正確識別 HTTPS 代理，解決手機 Safari Cookie 信任問題
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = "d2a89f3c71e54b8d9c2e1a6b0f4d8e9a2c3b5f7a9d1c0b8e"

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif'}
UPLOAD_FOLDER = 'static/uploads'

IS_LOCAL = True  # 在本機測試設為 True， 正式 False

# --- 伺服器端 Session 儲存目錄設定 ---
session_dir = os.path.join(os.getcwd(), 'flask_session')
if not os.path.exists(session_dir):
    os.makedirs(session_dir)

if IS_LOCAL:
    PHP_API_URL = "http://127.0.0.1:8000/api"
else:
    PHP_API_URL = "http://172.31.24.161/api"

# --- Config 設定 (解決 Safari 頻繁登出) ---
app.config.update(
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=180),
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_PATH='/',
    SESSION_COOKIE_SECURE=not IS_LOCAL,
    SESSION_COOKIE_SAMESITE='Lax',
    
    # 核心：啟動伺服器端檔案儲存，手機只存 ID
    SESSION_TYPE='filesystem',
    SESSION_FILE_DIR=session_dir,
    SESSION_FILE_THRESHOLD=5000
)
Session(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS
    
    
def render_page(template_body, **kwargs):
    html_layout = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title></title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            body {{ background-color: #f4f7f6; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
            .card {{ border-radius: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border: none; }}
            .border-bottom-dashed {{ border-bottom: 1px dashed #dee2e6; }}
            .barcode-box {{ background: white; padding: 15px; border: 1px dashed #ccc; margin-bottom: 10px; text-align: center; border-radius: 10px; }}
            .barcode-text {{ font-family: 'Courier New', monospace; font-size: 1.3rem; letter-spacing: 2px; font-weight: bold; color: #000; }}
            .btn-action {{ font-size: 0.75rem; padding: 2px 10px; border-radius: 20px; font-weight: bold; }}
            .modal-content {{ border: none; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
            .notice-box {{ background-color: #fffdf0; border-left: 5px solid #ffc107; border-radius: 12px; }}
        </style>
    </head>
    <body>
        <div class="container py-4">{{{{ template_body | safe }}}}</div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    return render_template_string(html_layout.replace("{{ template_body | safe }}", template_body), **kwargs)


DASHBOARD_CONTENT = r"""
<div class="container py-2" id="reconcile-app">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="fw-bold m-0">Hi, {{ session.get('name', 'Member') }}</h4>
        <div class="d-flex align-items-center">
            <button class="btn btn-sm btn-light text-primary fw-bold shadow-sm me-2" data-bs-toggle="modal" data-bs-target="#tutorialModal" style="border-radius: 8px; font-size: 0.75rem;">
                <i class="fas fa-question-circle me-1"></i>How to Pay?
            </button>
            <button class="btn btn-sm btn-outline-primary me-2 shadow-sm" data-bs-toggle="modal" data-bs-target="#pwModal" title="Change Password">
                <i class="fas fa-key"></i>
            </button>
            <a href="/logout" class="btn btn-sm btn-outline-danger shadow-sm">Logout</a>
        </div>
    </div>

    <div class="alert shadow-sm border-0 mb-4" style="background-color: #fffdf0; border-left: 4px solid #ffc107; border-radius: 12px;">
        <div class="d-flex align-items-center">
            <i class="fas fa-clock text-warning me-2"></i>
            <div class="small text-muted">
                <b>Payment Notice:</b> Please pay in order. Once a barcode is generated, you must complete the payment within <b>30 days</b>. Verification takes 5-7 working days.
            </div>
        </div>
    </div>

    {% for order in orders %}
    <div class="card mb-4 shadow-sm" style="border-radius: 15px;">
        <div class="card-body">
            <div class="d-flex justify-content-between mb-3 align-items-center">
                <h6 class="fw-bold m-0 text-secondary">Order: {{ order.order_no }}</h6>
                <span class="badge {% if order.status == 'Finished' or order.status == '已結清' %}bg-success{% else %}bg-warning text-dark{% endif %} rounded-pill shadow-sm">
                    {{ 'Finished' if (order.status == '已結清' or order.status == 'Finished') else 'Pending' }}
                </span>
            </div>

            <div class="p-2 bg-light rounded mb-3">
                <small class="text-muted d-block" style="font-size: 0.7rem;">Items:</small>
                <div class="fw-bold small">{{ order.items_text }}</div>
            </div>
                
            <div class="table-responsive">
                <table class="table table-sm align-middle">
                    <thead class="bg-light">
                        <tr class="small text-muted" style="font-size: 0.7rem;">
                            <th class="ps-2">Due Date</th>
                            <th>Amount</th>
                            <th class="text-end pe-2">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                    {% set flag = namespace(can_pay=true) %}
                    {% for s in order.payment_schedule %}
                    <tr class="border-bottom-dashed">
                        <td class="py-2 small text-muted text-nowrap">
                            {{ s.date[:10] if s.date else '-' }}
                        </td>
                        <td class="py-2 fw-bold text-nowrap">
                            ${{ "{:,.0f}".format(s.amount | float) }}
                        </td>
                        <td class="py-2 text-end pe-2">
                            {% if s.status == 'Paid' or s.status == '已支付' %}
                                <div class="text-success fw-bold" style="font-size: 0.75rem;">
                                    <i class="fas fa-check-circle"></i> Paid
                                </div>
                            {% else %}
                                {% if flag.can_pay %}
                                    <div class="text-end d-flex flex-column align-items-end">
                                        <button onclick="confirmBarcode('{{ s.id }}', '{{ s.has_barcode or s.barcode_1 }}')" 
                                                class="btn btn-sm {% if (s.has_barcode and s.has_barcode != '0') or (s.barcode_1 and s.barcode_1 != '0') %}btn-success{% else %}btn-primary{% endif %} shadow-sm fw-bold mb-1 w-100"
                                                style="font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; min-width: 100px;">
                                            <i class="fas {% if s.has_barcode or s.barcode_1 %}fa-eye{% else %}fa-magic{% endif %} me-1"></i>
                                            {{ 'View Barcode' if (s.has_barcode and s.has_barcode != '0') or (s.barcode_1 and s.barcode_1 != '0') else 'Get Barcode' }}
                                        </button>
                                        {% set flag.can_pay = false %} 
                                    </div>
                                {% else %}
                                    <div class="text-end">
                                        <span class="badge bg-light text-muted border fw-normal" style="font-size: 0.65rem; padding: 4px 8px;">Pending</span>
                                    </div>
                                {% endif %}
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
            </div>
    </div>
    {% endfor %}
</div>

<div class="modal fade" id="tutorialModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content border-0 shadow-lg" style="border-radius: 20px;">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold"><i class="fas fa-book-open text-primary me-2"></i>How to Pay?</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <div class="d-flex align-items-start mb-4">
                    <div class="badge bg-primary rounded-circle me-3 mt-1" style="width: 24px; height: 24px; min-width: 24px;">1</div>
                    <div class="w-100">
                        <h6 class="fw-bold mb-1">Payment Methods</h6>
                        <p class="small text-muted mb-2">
                            You can pay in person at our store or use a Barcode at convenience stores. 
                            <span class="d-block mt-1 fw-bold text-primary">Currently, these are the only two payment methods available.</span>
                        </p>
                        <div class="position-relative d-inline-block">
                            <img src="https://i.meee.com.tw/T28jvI7.jpg" class="img-fluid rounded-3 shadow-sm border" style="max-height: 180px;">
                            <div class="position-absolute top-50 start-50 translate-middle w-100 text-center" style="pointer-events: none; transform: translate(-50%, -50%) rotate(-15deg);">
                                <span class="badge bg-danger opacity-75 py-1 px-2 shadow-sm" style="font-size: 0.7rem;">EXAMPLE ONLY</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="d-flex align-items-start mb-4">
                    <div class="badge bg-primary rounded-circle me-3 mt-1" style="width: 24px; height: 24px; min-width: 24px;">2</div>
                    <div class="w-100">
                        <h6 class="fw-bold mb-1">Pay at Convenience Store</h6>
                        <p class="small text-muted mb-2">Present the 3 barcodes to the clerk. (7-11, FamilyMart, Hi-Life, OK Mart)</p>
                        
                        <img src="https://i.meee.com.tw/t6ZqMEX.jpg" class="d-block mb-2" style="height: 18px; opacity: 0.7;">
                        
                        <div class="position-relative d-inline-block">
                            <img src="https://i.meee.com.tw/MqGGGHw.jpg" class="img-fluid rounded-3 shadow-sm border" style="max-height: 180px;">
                            <div class="position-absolute top-50 start-50 translate-middle w-100 text-center" style="pointer-events: none; transform: translate(-50%, -50%) rotate(-15deg);">
                                <span class="badge bg-danger opacity-75 py-1 px-2 shadow-sm" style="font-size: 0.7rem;">EXAMPLE ONLY</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="d-flex align-items-start">
                    <div class="badge bg-primary rounded-circle me-3 mt-1" style="width: 24px; height: 24px; min-width: 24px;">3</div>
                    <div class="w-100">
                        <h6 class="fw-bold mb-1">Keep Receipt & Verification</h6>
                        <p class="small text-muted mb-0">
                            Please <b>keep your physical receipt</b> or take a photo and send it to our LINE. 
                        </p>
                        
                        <div class="alert alert-danger p-2 mt-2 mb-2 border-0 shadow-sm" style="border-radius: 10px; font-size: 0.75rem;">
                            <i class="fas fa-exclamation-triangle me-1"></i>
                            <b>DO NOT pay the same barcode twice.</b> If you need to make another payment, please wait for the first one to be verified before requesting a new barcode.
                        </div>

                        <p class="small text-muted">
                            <i class="fas fa-magic me-1 text-primary"></i> 
                            Verification takes <b>3-5 working days</b>, and the system will automatically reconcile your balance.
                        </p>
                    </div>
                </div>
            </div>
            <div class="modal-footer border-0">
                <button type="button" class="btn btn-primary w-100 fw-bold py-2" style="border-radius: 12px;" data-bs-dismiss="modal">Got it!</button>
            </div>
        </div>
    </div>
</div>
<script>
// 儲存準備要前往的 Barcode ID
let pendingBarcodeSid = null;

// 確認條碼邏輯
window.confirmBarcode = function(sid, hasBarcode) {
    const alreadyHas = hasBarcode && hasBarcode !== '0' && hasBarcode !== 'None' && hasBarcode !== 'False' && hasBarcode !== '';

    if (alreadyHas) {
        // 已有條碼，直接跳轉查看
        window.location.href = "/get_barcode/" + sid;
    } else {
        // 記錄要索取的 SID
        pendingBarcodeSid = sid;
        // 呼叫漂亮的有設計感 Modal
        var myModal = new bootstrap.Modal(document.getElementById('barcodeConfirmModal'));
        myModal.show();
    }
};

// 監聽漂亮 Modal 裡面的「Yes, Get it」按鈕
document.addEventListener('DOMContentLoaded', function() {
    var proceedBtn = document.getElementById('btn-proceed-barcode');
    if (proceedBtn) {
        proceedBtn.addEventListener('click', function() {
            if (pendingBarcodeSid) {
                // 按下確認後，鎖定按鈕避免重複點擊
                this.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
                this.disabled = true;
                // 跳轉前往取條碼
                window.location.href = "/get_barcode/" + pendingBarcodeSid;
            }
        });
    }
});

// 修改密碼邏輯
window.updatePassword = function() {
    var p1 = document.getElementById('new_pw').value;
    var p2 = document.getElementById('confirm_pw').value;
    
    if (!p1 || p1.length < 6) return alert("Password must be at least 6 characters.");
    if (p1 !== p2) return alert("Passwords do not match.");
    
    fetch('/update_password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: p1})
    }).then(function(res) {
        if (res.ok) { 
            alert("Password updated successfully!"); 
            location.reload(); 
        } else { 
            alert("Failed to update password. Please try again."); 
        }
    }).catch(function(err) {
        alert("Network error. Please try again later.");
    });
};
</script>
"""


BARCODE_PAGE = """
<style>
    /* 確保條碼在小螢幕手機上不會破版被截斷 */
    .barcode-svg {
        max-width: 100%;
        height: auto;
    }
</style>
<div class="container py-2" id="reconcile-app">
    {# --- Condition 1: If Barcode is Expired --- #}
    {% if b.is_expired %}
    <div class="card shadow border-0 p-4 text-center" style="border-radius: 20px; margin-top: 50px;">
        <div class="py-5">
            <i class="fas fa-exclamation-triangle text-danger mb-4" style="font-size: 4rem;"></i>
            <h4 class="fw-bold text-dark">Barcode Expired</h4>
            <p class="text-muted small px-3">This barcode has passed its payment deadline and is no longer valid for transaction.</p>
            
            <div class="px-3 mt-4">
                <a href="https://line.me/R/ti/p/你的LINE_ID" target="_blank" class="btn btn-danger w-100 py-2 fw-bold shadow-sm mb-3" style="border-radius: 12px; background-color: #e53e3e; border: none;">
                    <i class="fas fa-headset me-2"></i> CONTACT CUSTOMER SERVICE
                </a>
                
                <button onclick="goBack()" class="btn btn-light w-100 py-2 small fw-bold text-secondary border-0" style="border-radius: 12px; background-color: #f1f3f5;">
                    Back to Order List
                </button>
            </div>
        </div>
    </div>

    {# --- Condition 2: Normal Display --- #}
    {% else %}
    
    <div class="alert text-center border-0 py-2 mb-3 shadow-sm" style="background-color: #fff4e5; color: #d97706; border-radius: 10px;">
        <p class="small fw-bold mb-0">
            <i class="fas fa-sun me-2 fa-spin-hover"></i>Please turn screen brightness to MAXIMUM.
        </p>
    </div>

    <div class="notice-box p-3 mb-3 shadow-sm" style="background-color: #f8f9fa; border-radius: 15px; border-left: 4px solid #ffc107;">
        <h6 class="fw-bold text-dark mb-2"><i class="fas fa-info-circle text-warning me-1"></i> Payment Notice</h6>
        <ul class="small text-muted mb-0 ps-3">
            <li class="mb-1">After payment, please <b>take a photo of the receipt</b> and send to our <b>LINE</b>.</li>
            <li class="mb-1 text-danger">Verification takes <b>5 to 7 working days</b>.</li>
            <li>Status will <b>automatically update</b>.</li>
        </ul>
    </div>

    <div class="card mb-3 border-0 shadow-sm" style="background: linear-gradient(135deg, #00c6ff 0%, #0072ff 100%); border-radius: 15px;">
        <div class="card-body text-center text-white py-3">
            <div class="small opacity-75 mb-1">Total Amount</div>
            <div class="fs-1 fw-bold" style="letter-spacing: 1px;">${{ "{:,.0f}".format(b.amount | float) }}</div>
        </div>
    </div>

    <div class="card p-4 mb-4 shadow border-0" style="border-radius: 20px;">
        <div class="text-center mb-4">
            <svg id="barcode1" class="barcode-svg"></svg>
            <div class="fw-bold small text-muted" style="letter-spacing: 2px;">{{ b.barcode_1 }}</div>
        </div>
        <div class="text-center mb-4">
            <svg id="barcode2" class="barcode-svg"></svg>
            <div class="fw-bold small text-muted" style="letter-spacing: 2px;">{{ b.barcode_2 }}</div>
        </div>
        <div class="text-center mb-2">
            <svg id="barcode3" class="barcode-svg"></svg>
            <div class="fw-bold small text-muted" style="letter-spacing: 2px;">{{ b.barcode_3 }}</div>
        </div>
        
        <div class="mt-4 text-center border-top border-2 border-dashed pt-3">
            <div class="text-danger fw-bold small text-uppercase tracking-wide mb-1">Payment Deadline</div>
            <div class="fs-5 fw-bold text-dark">{{ b.expired_at }}</div>
        </div>
    </div>

    <div class="px-2 mb-5">
        <button onclick="goBack()" class="btn btn-outline-primary w-100 py-3 fw-bold shadow-sm" style="border-radius: 12px;">
            <i class="fas fa-arrow-left me-2"></i>Back to Order List
        </button>
    </div>
    {% endif %}
</div>

<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>
<script>
    {% if not b.is_expired %}
    // 優化：將 width 從 1 提升到 1.8，增加超商掃描槍的辨識率
    // margin 增加到 15 確保條碼兩側有足夠的留白 (Quiet Zone)
    const opt = { 
        format: "CODE39", 
        width: 1.8, 
        height: 65, 
        displayValue: false, 
        margin: 15,
        background: "#ffffff",
        lineColor: "#000000"
    };
    
    // 使用 setTimeout 確保 DOM 載入後再渲染，避免偶發的渲染失敗
    setTimeout(() => {
        JsBarcode("#barcode1", "{{ b.barcode_1 }}", opt);
        JsBarcode("#barcode2", "{{ b.barcode_2 }}", opt);
        JsBarcode("#barcode3", "{{ b.barcode_3 }}", opt);
    }, 100);
    {% endif %}

    function goBack() {
        window.location.href = '/dashboard?t=' + new Date().getTime();
    }
</script>
"""

LOGIN_CONTENT = """
<div class="row justify-content-center mt-5">
    <div class="col-md-5 col-12">     
        <div class="card p-4 shadow-sm" style="border-radius: 20px;">
            <h3 class="text-center mb-4 fw-bold">Login</h3>
            {% if error %}<div class="alert alert-danger py-2 small">{{ error }}</div>{% endif %}
            <form method="POST" action="/login" id="loginForm">
                <div class="mb-3">
                    <label class="form-label small fw-bold text-muted">Account</label>
                    <input type="text" id="login_account" name="account" class="form-control py-2" style="border-radius: 10px;" required>
                </div>
                <div class="mb-3">
                    <label class="form-label small fw-bold text-muted">Password</label>
                    <input type="password" name="password" class="form-control py-2" style="border-radius: 10px;" required>
                </div>
                <div class="mb-4 form-check">
                    <input type="checkbox" class="form-check-input" id="rememberMe" checked>
                    <label class="form-check-label small text-muted" for="rememberMe">Remember Account</label>
                </div>
                <button type="submit" class="btn btn-primary w-100 py-2 fw-bold shadow-sm" style="border-radius: 10px;">Login</button>
            </form>
        </div>
    </div>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {
    const accInput = document.getElementById('login_account');
    const saved = localStorage.getItem('member_account');
    if (saved) accInput.value = saved;
    document.getElementById('loginForm').addEventListener('submit', function() {
        if (document.getElementById('rememberMe').checked) localStorage.setItem('member_account', accInput.value);
        else localStorage.removeItem('member_account');
    });
});
</script>
"""

@app.route('/')
def index():
    if session.get('acc') and session.get('token'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))
    
    
@app.errorhandler(429)
def ratelimit_handler(e):
    return render_page(LOGIN_CONTENT, error="Too many attempts. Please wait 1 minute and try again.")
    
    
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("6 per minute", exempt_when=lambda: request.method == 'GET')
def login():
    if session.get('acc') and session.get('token'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        acc, pw = request.form.get('account'), request.form.get('password')
        try:
            res = requests.post(f"{PHP_API_URL}/login", json={"account": acc, "password": pw}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                session.permanent = True
                session['token'] = data['token']
                session['name'] = data['user']['name']
                session['acc'] = acc
                session['pw'] = pw
                session.modified = True # 確保寫入伺服器端
                return redirect(url_for('dashboard'))
            return render_page(LOGIN_CONTENT, error="Login Failed")
        except Exception as e:
            return render_page(LOGIN_CONTENT, error="Connection Error")
    return render_page(LOGIN_CONTENT, error=None)



@app.route('/dashboard')
def dashboard():
    if not session.get('acc') or not session.get('pw'):
        return redirect(url_for('login'))
    
    session.permanent = True
    def get_data(token):
        return requests.get(f"{PHP_API_URL}/my-orders", headers={"Authorization": f"Bearer {token}"}, timeout=5)

    try:
        if not session.get('token'): raise Exception("No Token")
        res = get_data(session['token'])
        
        if res.status_code == 401:
            re_login = requests.post(f"{PHP_API_URL}/login", json={"account": session['acc'], "password": session['pw']}, timeout=5)
            if re_login.status_code == 200:
                session['token'] = re_login.json()['token']
                session.modified = True
                res = get_data(session['token'])
            else:
                return redirect(url_for('login'))
        
        orders = res.json().get('orders', [])

        # --- 處理日期與條碼顯示邏輯 ---
        for order in orders:
            for s in order.get('payment_schedule', []):
                s['last_five'] = s.get('last_five', '')
                
                # 1. 檢查是否已經有條碼資料 (保留判斷，供前端區分 View/Get)
                has_existing_code = bool(s.get('barcode_1') and s.get('barcode_1') != '0') or \
                                    bool(s.get('has_barcode') and s.get('has_barcode') != '0')
                
                # 2. 隨時開放領取 (解除 20 天限制，讓前端 flag 決定順序即可)
                s['is_open'] = True
                
                # 3. 處理日期顯示字串
                if s.get('date'):
                    s['open_date_str'] = s['date'][:10]
                else:
                    s['open_date_str'] = 'Pending'

        # 存入 session 備用 (請確保縮排在 for 迴圈外)
        session['orders'] = orders
        session.modified = True

    except Exception as e:
        print(f"Dashboard Error: {e}")
        orders = []
        
    return render_page(DASHBOARD_CONTENT, orders=orders)






@app.route('/get_barcode/<payment_id>')
def get_barcode(payment_id):
    if not session.get('acc') or not session.get('pw'):
        return redirect(url_for('login'))
    
    try:
        # --- 1. 從 Session 找這筆資料做日期攔截 ---
        orders = session.get('orders', [])
        payment_info = None
        for order in orders:
            for s in order.get('payment_schedule', []):
                if str(s.get('id')) == str(payment_id):
                    payment_info = s
                    break
            if payment_info: break

        
        # --- 取消 20 天開放期攔截邏輯 (2026-04 依需求移除) ---
        # if payment_info and payment_info.get('date'):
        #     try:
        #         due_date = datetime.strptime(payment_info['date'][:10], '%Y-%m-%d')
        #         open_date = due_date - timedelta(days=20)
        #         if datetime.now() < open_date and not (payment_info.get('has_barcode') or payment_info.get('barcode_1')):
        #             return f"Available after: {open_date.strftime('%Y-%m-%d')}"
        #     except Exception as date_e:
        #         print(f"Date check error: {date_e}")
        
        # --- 2. Token 驗證與登入處理 ---
        token = session.get('token')
        if not token:
            re_login = requests.post(f"{PHP_API_URL}/login", json={"account": session['acc'], "password": session['pw']}, timeout=5)
            if re_login.status_code == 200:
                token = re_login.json()['token']
                session['token'] = token
            else: 
                return redirect(url_for('login'))

        # --- 3. 向 Laravel 請求條碼或跳轉連結 ---
        res = requests.post(
            f"{PHP_API_URL}/get-payment-url", 
            json={"payment_id": payment_id}, 
            headers={"Authorization": f"Bearer {token}"}, 
            timeout=5
        )

        # --- 4. 解析回傳結果 (關鍵修改處) ---
        data = res.json()
  
        # 💡 [關鍵：藍新模式] 偵測到跳轉指令，直接讓瀏覽器轉址到 Laravel 的渲染頁面
        if data.get('type') == 'redirect':
            pay_url = data.get('pay_url')
            return redirect(pay_url)

        # 💡 [速買配模式] 處理原本的 JSON 條碼顯示
        if res.status_code in [200, 400]:
            b = data.get('barcode')
            if b and b.get('barcode_1'):
                # 判定條碼是否過期
                b['is_expired'] = False
                expire_date_str = b.get('expired_at') or (payment_info.get('date') if payment_info else None)
                if expire_date_str:
                    try:
                        expire_dt = datetime.strptime(expire_date_str[:10], '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                        if datetime.now() > expire_dt:
                            b['is_expired'] = True
                    except: pass

                # 計算金額
                try: 
                    b['amount'] = int(b['barcode_3'][-5:])
                except: 
                    b['amount'] = 0
                    
                return render_page(BARCODE_PAGE, b=b)

        # --- 5. 錯誤處理與友善提示 ---
        error_msg = data.get('message', 'Unknown Error')
        
        if "trading control fail" in error_msg.lower():
            return render_page("""
                <div class="container text-center pt-4">
                    <h3 class="fw-bold">Payment Notice</h3>
                    <p class="mt-3">Barcode system is temporarily full.</p>                                     
                    <div class="alert alert-info py-3 my-4">
                        <strong>Try these instead:</strong><br>
                        1. Bank Transfer<br>
                        2. <b>Pay In-Store</b> (Cash)<br>
                        3. <b>Try again</b> in 2-3 days
                    </div>
                    <a href="/dashboard" class="btn btn-primary btn-lg w-100 py-3 shadow">Back to Dashboard</a>
                </div>
            """)
                    
        return f"Error: {error_msg}"
        
    except Exception as e: 
        print(f"Get Barcode Critical Error: {e}") 
        return "System Error"


        
@app.route('/payment/callback/proxy', methods=['POST'])
def payment_callback_proxy():
    try:
        # 1️⃣ 原始 body（完全不解析）
        raw_body = request.get_data()

        # 2️⃣ 原始 headers
        content_type = request.headers.get("Content-Type", "")

        # 3️⃣ 判斷金流（只用字串判斷，不解析）
        body_text = raw_body.decode("utf-8", errors="ignore")

        if "MerchantID" in body_text:
            target_url = f"{PHP_API_URL}/payment/callback/ecpay"

        elif "Smseid" in body_text or "Data_id" in body_text:
            target_url = f"{PHP_API_URL}/payment/callback/smilepay"

        else:
            print("Unknown provider", flush=True)
            return "Unknown provider", 400

        # 4️⃣ 保留原始 Content-Type
        headers = {
            "Content-Type": content_type
        }

        # 5️⃣ 原封不動轉發
        php_response = requests.post(
            target_url,
            data=raw_body,
            headers=headers,
            timeout=20
        )

        return Response(
            php_response.text,
            status=php_response.status_code,
            mimetype="text/plain"
        )

    except Exception as e:
        print(f"Proxy Error: {str(e)}", flush=True)
        return "Proxy Error", 500        
        
        
@app.route('/cancel_transfer', methods=['POST'])
def cancel_transfer():
    data = request.json
    schedule_id = data.get('schedule_id')

    if not schedule_id:
        return jsonify({"status": "error", "message": "Missing schedule ID"}), 400

    try:
        # 呼叫 PHP API 進行取消 (請確認 PHP 端有對應此功能的 URL)
        response = requests.post(
            f"{PHP_API_URL}/cancel-transfer-report", 
            json={"order_payment_id": int(schedule_id)},
            headers={"Authorization": f"Bearer {session.get('token')}"},
            timeout=10
        )
        
        if response.status_code == 200:
            return jsonify({"status": "success"})
        else:
            try:
                result = response.json()
            except:
                result = {"message": response.text}
            return jsonify({"status": "error", "message": result.get('message', 'PHP Server Error')}), response.status_code
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

 
@app.route('/submit_transfer', methods=['POST'])
def submit_transfer():
    # 1. 讀 form
    schedule_id = request.form.get('schedule_id')
    order_no = request.form.get('order_no')
    amount = request.form.get('amount')
    last_five = request.form.get('last_five')

    try:
        payload = {
            "order_payment_id": int(schedule_id),
            "order_no": str(order_no),
            "amount": float(amount),
            "last_five": str(last_five)
        }
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid data format"}), 400

    # 2. 讀圖片
    receipt_file = request.files.get('receipt_img')
    if receipt_file:
        if not allowed_file(receipt_file.filename):
            return jsonify({"status": "error", "message": "Invalid image type"}), 400

        filename = secure_filename(receipt_file.filename)
        filename = f"{order_no}_{schedule_id}_{int(time.time())}_{filename}"
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        save_path = os.path.join(UPLOAD_FOLDER, filename)
        receipt_file.save(save_path)

        # 加到 payload 裡 (如果 PHP API 需要)
        # 你可以改成傳送 file
        files = {'receipt_img': open(save_path, 'rb')}
    else:
        files = None

    # 3. 傳到 PHP API
    try:
        response = requests.post(
            f"{PHP_API_URL}/save-transfer-report",
            data=payload,
            files=files,
            headers={"Authorization": f"Bearer {session.get('token')}"},
            timeout=10
        )
        result = response.json() if response.text else {"message": "No response"}

        if response.status_code == 200:
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": result.get('message', 'PHP Server Error')}), response.status_code

    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Connection timeout"}), 504
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
        
        
    
@app.route('/update_password', methods=['POST'])
def update_password():
    if not session.get('token'): return {"message": "Unauthorized"}, 401
    try:
        res = requests.post(f"{PHP_API_URL}/update-password", json=request.json, headers={"Authorization": f"Bearer {session['token']}"}, timeout=5)
        if res.status_code == 200:
            session.clear()
            return {"message": "Success"}, 200
        return res.json(), res.status_code
    except: return {"message": "Error"}, 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)