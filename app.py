import os
from flask import Flask, render_template_string, request, redirect, url_for, session
import requests
from datetime import timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_session import Session # 伺服器端執行: pip install flask-session

app = Flask(__name__)
# 讓 Flask 正確識別 HTTPS 代理，解決手機 Safari Cookie 信任問題
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = "d2a89f3c71e54b8d9c2e1a6b0f4d8e9a2c3b5f7a9d1c0b8e"

IS_LOCAL = False  # 在本機測試設為 True，搬到 AWS 設為 False

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

def render_page(template_body, **kwargs):
    html_layout = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Member Payment System</title>
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

DASHBOARD_CONTENT = """
<div class="container py-2">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="fw-bold m-0">Hi, {{ session.get('name', 'Member') }}</h4>
        <div>
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
                <b>Payment Notice:</b> Verification takes <b>5-7 working days</b> after payment. Your status will update automatically.
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

            <div class="fw-bold mb-2 text-primary small"><i class="fas fa-list-ol me-1"></i> Payment Schedule</div>
            
            <div class="table-responsive">
                <table class="table table-sm align-middle">
                    <thead class="bg-light">
                        <tr class="small text-muted" style="font-size: 0.7rem;">
                            <th class="ps-2">Due Date</th>
                            <th>Amount</th>
                            <th class="text-end pe-2">Action / Status</th>
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
                                    <div class="text-success" style="font-size: 0.65rem; margin-top: -2px;">
                                        {{ s.actual_remittance_date[:10] if s.actual_remittance_date else '' }}
                                    </div>
                                {% else %}
                                    {% if flag.can_pay %}
                                        <a href="/get_barcode/{{ s.id }}" 
                                           class="btn btn-sm {% if s.has_barcode or s.barcode_1 %}btn-success{% else %}btn-primary{% endif %} shadow-sm fw-bold"
                                           style="font-size: 0.7rem; padding: 2px 8px; border-radius: 6px;">
                                           <i class="fas {% if s.has_barcode or s.barcode_1 %}fa-eye{% else %}fa-magic{% endif %} me-1"></i>
                                           {{ 'View Barcode' if (s.has_barcode or s.barcode_1) else 'Get Barcode' }}
                                        </a>
                                        {% set flag.can_pay = false %}
                                    {% else %}
                                        <div class="text-end">
                                            <span class="badge bg-light text-muted border fw-normal" style="font-size: 0.65rem; padding: 4px 8px;">Pending</span>
                                            <div class="text-muted" style="font-size: 0.55rem; margin-top: 2px; letter-spacing: -0.2px;">Wait 5-7 days for sync</div>
                                        </div>
                                    {% endif %}
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <div class="mt-3 pt-2 border-top d-flex justify-content-between align-items-center">
                <small class="text-muted">Balance: <span class="text-danger fw-bold">${{ "{:,.0f}".format(order.balance) }}</span></small>
                <small class="text-muted" style="font-size: 0.7rem;">Term: {{ order.period }}</small>
            </div>
        </div>
    </div>
    {% endfor %}
</div>

<div class="modal fade" id="pwModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content shadow" style="border-radius: 20px;">
            <div class="modal-header border-0 pb-0">
                <h5 class="modal-header-title fw-bold">Update Password</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <div class="mb-3">
                    <label class="small fw-bold text-muted">New Password</label>
                    <input type="password" id="new_pw" class="form-control py-2 shadow-sm" style="border-radius: 10px;" placeholder="Min 6 characters">
                </div>
                <div class="mb-3">
                    <label class="small fw-bold text-muted">Confirm Password</label>
                    <input type="password" id="confirm_pw" class="form-control py-2 shadow-sm" style="border-radius: 10px;" placeholder="Type again">
                </div>
            </div>
            <div class="modal-footer border-0">
                <button type="button" class="btn btn-primary w-100 py-2 fw-bold shadow-sm" style="border-radius: 10px;" onclick="updatePassword()">Save New Password</button>
            </div>
        </div>
    </div>
</div>
<script>
function updatePassword() {
    const pw = document.getElementById('new_pw').value;
    const confirmPw = document.getElementById('confirm_pw').value;
    if (pw.length < 6) { alert("Min 6 characters"); return; }
    if (pw !== confirmPw) { alert("Passwords do not match!"); return; }

    fetch('/update_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw })
    })
    .then(async res => {
        if (res.ok) {
           alert("Password updated! Please login again.");
           window.location.href = '/login';
        } else {
            alert("Update Failed");
        }
    });
}
</script>
"""

BARCODE_PAGE = """
<div class="text-center mb-4">
    <p class="text-danger small fw-bold">
        <i class="fas fa-sun me-1"></i>Please turn your screen brightness to maximum and present this to the clerk.
    </p>
</div>

<div class="card mb-3 border-0 shadow-sm" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 15px;">
    <div class="card-body text-center text-white py-3">
        <div class="small opacity-75">Total Amount Due</div>
        <div class="fs-2 fw-bold">${{ "{:,.0f}".format(b.amount | float) }}</div>
    </div>
</div>

<div class="card p-3 mb-4 shadow border-0" style="border-radius: 20px;">
    <div class="text-center mb-4"><svg id="barcode1"></svg><div class="fw-bold small">{{ b.barcode_1 }}</div></div>
    <div class="text-center mb-4"><svg id="barcode2"></svg><div class="fw-bold small">{{ b.barcode_2 }}</div></div>
    <div class="text-center mb-4"><svg id="barcode3"></svg><div class="fw-bold small">{{ b.barcode_3 }}</div></div>
    <div class="mt-2 text-center border-top pt-3">
        <div class="text-danger fw-bold small">Payment Deadline</div>
        <div class="fs-5 fw-bold text-dark">{{ b.expired_at }}</div>
    </div>
</div>

<div class="notice-box p-3 mb-4 shadow-sm">
    <h6 class="fw-bold text-dark mb-2"><i class="fas fa-info-circle text-warning me-1"></i> Payment Notice</h6>
    <ul class="small text-muted mb-0 ps-3">
        <li class="mb-2">After payment, please <b>take a photo of the receipt</b> and send to our <b>LINE</b>.</li>
        <li class="mb-2">Verification takes <b>5 to 7 working days</b>.</li>
        <li>Status will <b>automatically update</b>. Thank you!</li>
    </ul>
</div>

<div class="px-2 mb-5">
    <button onclick="goBack()" class="btn btn-outline-primary w-100 py-3 fw-bold rounded-3 shadow-sm">
        <i class="fas fa-arrow-left me-2"></i>Back to Order List
    </button>
</div>

<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>
<script>
    const opt = { format: "CODE39", width: 1, height: 60, displayValue: false, margin: 10 };
    JsBarcode("#barcode1", "{{ b.barcode_1 }}", opt);
    JsBarcode("#barcode2", "{{ b.barcode_2 }}", opt);
    JsBarcode("#barcode3", "{{ b.barcode_3 }}", opt);
    function goBack() { 
        if (document.referrer.includes('dashboard')) window.history.back();
        else window.location.href = '/dashboard';
    }
</script>
"""

LOGIN_CONTENT = """
<div class="row justify-content-center mt-5">
    <div class="col-md-5 col-12">
        <div class="card p-4 shadow-sm" style="border-radius: 20px;">
            <h3 class="text-center mb-4 fw-bold">Member Login</h3>
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

@app.route('/login', methods=['GET', 'POST'])
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
    except:
        orders = []
    return render_page(DASHBOARD_CONTENT, orders=orders)

@app.route('/get_barcode/<payment_id>')
def get_barcode(payment_id):
    if not session.get('acc') or not session.get('pw'):
        return redirect(url_for('login'))
    try:
        if not session.get('token'):
            re_login = requests.post(f"{PHP_API_URL}/login", json={"account": session['acc'], "password": session['pw']}, timeout=5)
            if re_login.status_code == 200:
                session['token'] = re_login.json()['token']
                session.modified = True
            else: return redirect(url_for('login'))

        res = requests.post(f"{PHP_API_URL}/get-payment-url", json={"payment_id": payment_id}, headers={"Authorization": f"Bearer {session['token']}"}, timeout=5)
        if res.status_code == 401:
            re_login = requests.post(f"{PHP_API_URL}/login", json={"account": session['acc'], "password": session['pw']}, timeout=5)
            if re_login.status_code == 200:
                session['token'] = re_login.json()['token']
                session.modified = True
                res = requests.post(f"{PHP_API_URL}/get-payment-url", json={"payment_id": payment_id}, headers={"Authorization": f"Bearer {session['token']}"}, timeout=5)
            else: return redirect(url_for('login'))

        data = res.json()
        if res.status_code in [200, 400]:
            b = data.get('barcode')
            if b and b.get('barcode_3'):
                try: b['amount'] = int(b['barcode_3'][-5:])
                except: b['amount'] = 0
                return render_page(BARCODE_PAGE, b=b)
        return f"Error: {data.get('message', 'Unknown Error')}"
    except: return "System Error"

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