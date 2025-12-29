from flask import Flask, render_template_string, request, redirect, url_for, session
import requests

app = Flask(__name__)
app.secret_key = "secure_payment_secret_999"

# Update this to your PHP API endpoint
PHP_API_URL = "http://127.0.0.1:8000/api"

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
            /* 讓 Modal 看起來更現代 */
            .modal-content {{ border: none; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
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
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h4 class="fw-bold m-0">Hi, {{ session.get('name', 'Member') }}</h4>
        <div>
            <button class="btn btn-sm btn-outline-primary me-2 shadow-sm" data-bs-toggle="modal" data-bs-target="#pwModal" title="Change Password">
                <i class="fas fa-key"></i>
            </button>
            <a href="/logout" class="btn btn-sm btn-outline-danger shadow-sm">Logout</a>
        </div>
    </div>

    {% for order in orders %}
    <div class="card mb-4">
        <div class="card-body">
            <div class="d-flex justify-content-between mb-3">
                <h6 class="fw-bold">No: {{ order.order_no }}</h6>
                <span class="badge {% if order.status == 'Finished' or order.status == '已結清' %}bg-success{% else %}bg-warning text-dark{% endif %} rounded-pill">
                    {{ 'Finished' if (order.status == '已結清' or order.status == 'Finished') else 'Pending' }}
                </span>
            </div>

            <div class="p-2 bg-light rounded mb-3">
                <small class="text-muted d-block">Items:</small>
                <div class="fw-bold small">{{ order.items_text }}</div>
            </div>

            <div class="fw-bold mb-2 text-primary small"><i class="fas fa-list-ol me-1"></i> Payment Schedule</div>
            <div class="table-responsive">
                <table class="table table-sm align-middle">
                    <thead class="bg-light">
                        <tr class="small text-muted">
                            <th class="ps-2">Due Date</th>
                            <th>Amount</th>
                            <th class="text-center">Paid Date</th> 
                            <th class="text-end pe-2">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% set flag = namespace(can_pay=true) %}
                        {% for s in order.payment_schedule %}
                        <tr class="border-bottom-dashed">
                            <td class="py-2 small text-muted">{{ s.date[:10] if s.date else '-' }}</td>
                            <td class="py-2 fw-bold">${{ "{:,.0f}".format(s.amount | float) }}</td>
                            
                            <td class="py-2 small text-center">
                                {% if s.status == 'Paid' or s.status == '已支付' %}
                                    <span class="text-success fw-bold">
                                        {{ s.actual_remittance_date[:10] if s.actual_remittance_date else 'Success' }}
                                    </span>
                                {% else %}
                                    <span class="text-muted" style="opacity: 0.5;">-</span>
                                {% endif %}
                            </td>

                            <td class="py-2 text-end pe-2">
                                {% if s.status == 'Paid' or s.status == '已支付' %}
                                    <span class="text-success small fw-bold"><i class="fas fa-check-circle"></i> Paid</span>
                                {% else %}
                                    {% if flag.can_pay %}
                                        {% if s.has_barcode or s.barcode_1 %}
                                            <a href="/get_barcode/{{ s.id }}" 
                                               class="btn btn-sm btn-success btn-action shadow-sm">
                                               <i class="fas fa-eye me-1"></i>View Barcode
                                            </a>
                                        {% else %}
                                            <a href="/get_barcode/{{ s.id }}" 
                                               class="btn btn-sm btn-primary btn-action shadow-sm">
                                               <i class="fas fa-magic me-1"></i>Get Barcode
                                            </a>
                                        {% endif %}
                                        {% set flag.can_pay = false %}
                                    {% else %}
                                        <span class="badge bg-light text-muted border" style="font-size: 0.7rem;">Pending</span>
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
                <small class="text-muted">Installments: {{ order.period }}</small>
            </div>
        </div>
    </div>
    {% endfor %}
</div>

<div class="modal fade" id="pwModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content shadow" style="border-radius: 20px; border: none;">
            <div class="modal-header border-0 pb-0">
                <h5 class="modal-title fw-bold">Update Password</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
                <p class="small text-muted mb-3">Please enter your new login password.</p>
                <input type="password" id="new_pw" class="form-control py-2" style="border-radius: 10px;" placeholder="Min 6 characters">
            </div>
            <div class="modal-footer border-0">
                <button type="button" class="btn btn-primary w-100 py-2 fw-bold" style="border-radius: 10px;" onclick="updatePassword()">Save New Password</button>
            </div>
        </div>
    </div>
</div>

<script>
function updatePassword() {
    const pw = document.getElementById('new_pw').value;
    if (pw.length < 6) {
        alert("Password must be at least 6 characters");
        return;
    }
    
    // 呼叫 Python 後端
    fetch('/update_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw })
    })
    .then(async res => {
        const data = await res.json();
        if (res.ok) {
            alert("Password updated successfully!");
            location.reload();
        } else {
            alert("Error: " + (data.message || "Failed to update"));
        }
    })
    .catch(err => alert("Connection Error"));
}
</script>
"""

BARCODE_PAGE = """
<div class="text-center mb-4">
    <h4 class="fw-bold">Convenience Store Barcode</h4>
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
    <div class="text-center mb-4">
        <svg id="barcode1"></svg>
        <div class="fw-bold mt-1" style="letter-spacing: 2px; font-family: monospace;">{{ b.barcode_1 }}</div>
    </div>

    <div class="text-center mb-4">
        <svg id="barcode2"></svg>
        <div class="fw-bold mt-1" style="letter-spacing: 2px; font-family: monospace;">{{ b.barcode_2 }}</div>
    </div>

    <div class="text-center mb-4">
        <svg id="barcode3"></svg>
        <div class="fw-bold mt-1" style="letter-spacing: 2px; font-family: monospace;">{{ b.barcode_3 }}</div>
    </div>

    <div class="mt-2 text-center border-top pt-3">
        <div class="text-danger fw-bold small">Payment Deadline</div>
        <div class="fs-5 fw-bold text-dark">{{ b.expired_at }}</div>
    </div>
</div>

<div class="px-2">
    <a href="/dashboard" class="btn btn-outline-primary w-100 py-3 fw-bold rounded-3">
        <i class="fas fa-arrow-left me-2"></i>Back to Order List
    </a>
</div>

<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>
<script>
    const options = {
        format: "CODE128",
        width: 2,
        height: 50,
        displayValue: false,
        margin: 10
    };
    JsBarcode("#barcode1", "{{ b.barcode_1 }}", options);
    JsBarcode("#barcode2", "{{ b.barcode_2 }}", options);
    JsBarcode("#barcode3", "{{ b.barcode_3 }}", options);
</script>
"""

LOGIN_CONTENT = """
<div class="row justify-content-center mt-5">
    <div class="col-md-5 col-12">
        <div class="card p-4">
            <h3 class="text-center mb-4">Member Login</h3>
            {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
            <form method="POST" action="/login">
                <div class="mb-3">
                    <label class="form-label">Account</label>
                    <input type="text" name="account" class="form-control" placeholder="Enter account" required>
                </div>
                <div class="mb-3">
                    <label class="form-label">Password</label>
                    <input type="password" name="password" class="form-control" placeholder="Enter password" required>
                </div>
                <button type="submit" class="btn btn-primary w-100 py-2 fw-bold">Login</button>
            </form>
        </div>
    </div>
</div>
"""

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        acc, pw = request.form.get('account'), request.form.get('password')
        try:
            res = requests.post(f"{PHP_API_URL}/login", json={"account": acc, "password": pw}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                session['token'], session['name'] = data['token'], data['user']['name']
                return redirect(url_for('dashboard'))
            return render_page(LOGIN_CONTENT, error="Login Failed")
        except: return render_page(LOGIN_CONTENT, error="Connection Error")
    return render_page(LOGIN_CONTENT, error=None)

@app.route('/dashboard')
def dashboard():
    if 'token' not in session: return redirect(url_for('login'))
    headers = {"Authorization": f"Bearer {session['token']}"}
    try:
        res = requests.get(f"{PHP_API_URL}/my-orders", headers=headers, timeout=5)
        orders = res.json().get('orders', [])
    except: orders = []
    return render_page(DASHBOARD_CONTENT, orders=orders)


@app.route('/update_password', methods=['POST'])
def update_password():
    if 'token' not in session: return {"message": "Unauthorized"}, 401
    headers = {"Authorization": f"Bearer {session['token']}"}
    pw_data = request.json
    try:
        # 轉發給 PHP 端 API (請確認 PHP 端已有對應的 /update-password)
        res = requests.post(f"{PHP_API_URL}/update-password", json=pw_data, headers=headers, timeout=5)
        return res.json(), res.status_code
    except:
        return {"message": "Connection Error"}, 500
        
        
@app.route('/get_barcode/<payment_id>')
def get_barcode(payment_id):
    if 'token' not in session: return redirect(url_for('login'))
    headers = {"Authorization": f"Bearer {session['token']}"}
    try:
        res = requests.post(f"{PHP_API_URL}/get-payment-url", json={"payment_id": payment_id}, headers=headers, timeout=5)
        data = res.json()
        
        print(f"--- Debug Info ---")
        print(f"Status: {res.status_code}")
        print(f"Payload: {res.text}")

        if res.status_code == 200 or res.status_code == 400:
            barcode_data = data.get('barcode')
            if barcode_data and barcode_data.get('barcode_3'):
                try:
                    # Extract last 5 digits from barcode_3 as amount
                    raw_amount = barcode_data['barcode_3'][-5:]
                    barcode_data['amount'] = int(raw_amount)
                except:
                    barcode_data['amount'] = 0
                
                return render_page(BARCODE_PAGE, b=barcode_data)

        return f"Error: {data.get('message', 'Unknown Error')}"
    except Exception as e:
        print(f"Error: {str(e)}")
        return "System Error"

# 請檢查 app.py 裡是否有這一段
@app.route('/payment/callback/proxy', methods=['POST'])
def payment_callback_proxy():
    payment_data = request.form.to_dict()
    print("--- Received Callback Proxy ---")
    try:
        # 轉發給 PHP
        res = requests.post(f"{PHP_API_URL}/payment/callback", data=payment_data, timeout=10)
        return res.text
    except Exception as e:
        return f"Proxy Error: {str(e)}", 500


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)