import os                          
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
import requests
from datetime import datetime,  timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_session import Session # 伺服器端執行: pip install flask-session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import time
from werkzeug.utils import secure_filename

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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS
    
    
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


DASHBOARD_CONTENT = r"""
<div class="container py-2" id="reconcile-app">
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
                                <div class="text-success" style="font-size: 0.65rem; margin-top: -2px;">
                                    {{ s.actual_remittance_date[:10] if s.actual_remittance_date else '' }}
                                </div>
                            {% else %}
                                {% if flag.can_pay %}
                                    <div class="text-end d-flex flex-column align-items-end">
                                    {% if not s.has_report %}
                                        {% if s.is_open or s.has_barcode or s.barcode_1 %}
                                            <a href="/get_barcode/{{ s.id }}" 
                                               class="btn btn-sm {% if (s.has_barcode and s.has_barcode != '0') or (s.barcode_1 and s.barcode_1 != '0') %}btn-success{% else %}btn-primary{% endif %} shadow-sm fw-bold mb-1 w-100"
                                               style="font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; min-width: 100px;">
                                               <i class="fas {% if s.has_barcode or s.barcode_1 %}fa-eye{% else %}fa-magic{% endif %} me-1"></i>
                                               {{ 'View Barcode' if (s.has_barcode and s.has_barcode != '0') or (s.barcode_1 and s.barcode_1 != '0') else 'Get Barcode' }}
                                            </a>
                                        {% else %}
                                            <div class="text-muted mb-1" style="font-size: 0.6rem;">
                                                <i class="fas fa-clock me-1"></i>Barcode: {{ s.open_date_str if s.open_date_str else 'Soon' }}
                                            </div>
                                        {% endif %}
                                    {% endif %}
                                        {% if s.has_report %}
                                      <button class="btn btn-sm btn-outline-primary w-100 shadow-sm fw-bold" 
                                            style="font-size: 0.7rem; padding: 2px 8px; border-radius: 6px;"
                                            onclick="viewSubmittedInfo('{{ order.order_no }}', '{{ s.amount }}', '{{ s.last_five if s.last_five else '' }}','{{ s.receipt_url }}')">
                                        <i class="fas fa-info-circle me-1"></i> View Info
                                    </button>
                                                <div class="text-center mt-1">
                                                <a href="javascript:void(0)" class="text-muted small text-decoration-underline" 
                                                   onclick="cancelReport('{{ s.id }}')" style="font-size: 0.65rem;">
                                                   Cancel
                                                </a>
                                            </div>
                                            <div class="text-danger mt-1 fw-bold" style="font-size: 0.62rem; letter-spacing: -0.2px;">
                                                   <i class="fas fa-exclamation-circle me-1"></i>Verification: 5-7 working days
                                            </div>
                                        {% else %}
                                            <button class="btn btn-sm btn-outline-info fw-bold w-100 shadow-sm btn-trigger-transfer" 
                                                    style="font-size: 0.7rem; padding: 2px 8px; border-radius: 6px;"
                                                    data-bs-toggle="modal" 
                                                    data-bs-target="#transferModal"
                                                    data-order="{{ order.order_no }}"
                                                    data-sid="{{ s.id }}"
                                                    data-amount="{{ s.amount }}">
                                                <i class="fas fa-university me-1"></i> Transfer
                                            </button>
                                        {% endif %}
                                        
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

            <div class="mt-3 pt-2 border-top d-flex justify-content-between align-items-center">
                <small class="text-muted">               
                    {% if order.balance <= 0 %}
                        <span class="text-success fw-bold"><i class="fas fa-check-double me-1"></i>Finished</span>
                    {% else %}
                         Balance: <span class="text-danger fw-bold">${{ "{:,.0f}".format(order.balance) }}</span>
                    {% endif %}
                </small>
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


<div class="modal fade" id="transferModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content shadow-lg" style="border-radius: 20px; border: none;">
            <div class="modal-header border-0 pb-0">
                <h5 class="fw-bold"><i class="fas fa-university text-primary me-2"></i>Transfer Info</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body text-start">
                <div class="p-3 mb-3" style="background-color: #f0faff; border-radius: 12px; border: 1px dashed #0dcaf0;">
                    <div class="small text-muted mb-1">Our Account:</div>
                    <div class="fw-bold text-dark">
                        Bank Name: <span class="text-primary">CTBC (822)</span><br>
                       Account: <span class="text-primary" id="bank-account-num">129542011991</span>                       
                        <button class="btn btn-sm p-0 ms-1 text-secondary" onclick="copyAccountNumber()" title="Copy Account">
                            <i class="fas fa-copy" id="copy-icon"></i>
                            <span id="copy-text" style="font-size: 0.65rem; display: none;" class="text-success fw-bold">Copied!</span>
                        </button>     
                          <div class="mt-2 mb-2 fw-bold" style="color: #0d6efd; font-size: 0.75rem; line-height: 1.4;">
                            <i class="fas fa-camera me-1"></i>Done transfer? Please upload your receipt below.
                            <div class="fw-normal text-muted" style="font-size: 0.65rem; margin-top: 2px;">
                                (Not required for Barcode payments; it's verified automatically.)
                            </div>
                        </div>     
                    </div> 
                </div>
                <input type="hidden" id="report_sid">
                <div class="mb-3">
                    <label class="small fw-bold text-muted">Order No.</label>
                    <input type="text" id="report_order_no" class="form-control bg-light" readonly>
                </div>
                <div class="mb-3">
                    <label class="small fw-bold text-muted">Amount Paid ($)</label>
                    <input type="number" id="report_amount" class="form-control">
                </div>
                <div class="mb-3">
                    <label class="small fw-bold text-muted">Your ATM Account Last 5 Digits</label>
                    <input type="text" id="report_five" class="form-control" placeholder="e.g. 12345" maxlength="5">
                    <div class="form-text text-muted" style="font-size: 0.7rem;">
                        * For Cash Deposit, please enter <span class="fw-bold text-primary">00000</span>.
                    </div>
                </div>
              <div class="mb-3">
                <label class="small fw-bold text-danger mb-1 d-block">
                    <i class="fas fa-camera me-1"></i>After transferring, please upload your receipt.
                </label>
                <div class="custom-file-upload">
                    <input type="file" id="receipt_img" class="d-none" accept="image/*" 
                           onchange="document.getElementById('file-status').innerText = 'Selected: ' + this.files[0].name">
                    
                    <label for="receipt_img" class="btn btn-outline-primary w-100 py-2 d-flex align-items-center justify-content-center" style="border-style: dashed;">
                        <i class="fas fa-cloud-upload-alt me-2"></i>Choose Receipt Image
                    </label>
                    
                    <div id="preview-wrapper" class="d-none mt-2 text-center">
                        <img id="receipt-preview" src="" alt="Preview" class="img-thumbnail" style="max-height: 150px; border-radius: 8px;">
                    </div>
                    
                    
                    
                    <div id="file-status" class="form-text text-muted text-center mt-1" style="font-size: 0.7rem;">
                        No file chosen
                    </div>
                </div>   

                
            </div>

            </div>
            <div class="modal-footer border-0">
                <button type="button" class="btn btn-primary w-100 py-3 fw-bold" id="btn-submit-payment" style="border-radius: 12px;">Submit</button>
            </div>
        </div>
    </div>   
</div>
<div class="modal fade" id="receiptModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content" style="border-radius: 20px;">
      <div class="modal-header border-0">
        <h5 class="modal-title fw-bold">Payment Info</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <p id="modalInfo"></p>
        <img id="modalImg" src="" alt="Receipt Image" style="max-width: 320px; max-height: 400px; width: auto; height: auto; display:none; margin: 0 auto;" />
      </div>
      <div class="modal-footer border-0">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
      </div>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/heic2any@0.0.4/dist/heic2any.min.js"></script>
<script>
let finalFileToUpload = null;

document.getElementById('receipt_img').addEventListener('change', async function(e) {
    const file = e.target.files[0];
    if (!file) return;

    const subBtn = document.getElementById('btn-submit-payment');
    const statusText = document.getElementById('file-status');
    const previewWrapper = document.getElementById('preview-wrapper');
    const previewImg = document.getElementById('receipt-preview');

    // 1. 進入處理狀態：鎖定按鈕
    if (subBtn) {
        subBtn.disabled = true;
        subBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>處理照片中...';
    }

    let workingBlob = file;

    // 2. 如果是 iPhone HEIC 格式，先轉成標準 Blob
    if (file.type === "image/heic" || /\.heic$/i.test(file.name)) {
        try {
            console.log("Detecting HEIC, converting...");
            workingBlob = await heic2any({
                blob: file,
                toType: "image/jpeg",
                quality: 0.8
            });
            if (Array.isArray(workingBlob)) workingBlob = workingBlob[0];
        } catch (err) {
            console.error("HEIC Conversion Error:", err);
        }
    }

    // 3. 使用 Canvas 進行尺寸壓縮 (Resize)
    const img = new Image();
    const reader = new FileReader();

    reader.onload = function(event) {
        img.src = event.target.result;
        img.onload = function() {
            const canvas = document.createElement('canvas');
            let width = img.width;
            let height = img.height;

            // 限制最大邊長為 1280 像素，這能讓 5MB 照片變成 500KB 左右
            const MAX_WIDTH_HEIGHT = 1280;
            if (width > height) {
                if (width > MAX_WIDTH_HEIGHT) {
                    height *= MAX_WIDTH_HEIGHT / width;
                    width = MAX_WIDTH_HEIGHT;
                }
            } else {
                if (height > MAX_WIDTH_HEIGHT) {
                    width *= MAX_WIDTH_HEIGHT / height;
                    height = MAX_WIDTH_HEIGHT;
                }
            }

            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, width, height);

            // 轉成最終要上傳的 JPG Blob
            canvas.toBlob(function(finalBlob) {
                // 封裝成新的 File 物件供上傳
                finalFileToUpload = new File([finalBlob], "receipt.jpg", { type: "image/jpeg" });

                // 4. 更新預覽圖與 UI
                previewImg.src = canvas.toDataURL('image/jpeg');
                previewWrapper.classList.remove('d-none');

                if (subBtn) {
                    subBtn.disabled = false;
                    subBtn.innerHTML = 'Submit';
                }
                
                // 顯示壓縮後的資訊供確認
                const fileSizeMB = (finalBlob.size / 1024 / 1024).toFixed(2);
                console.log("Image optimized for upload:", finalFileToUpload);
            }, 'image/jpeg', 0.7); // 0.7 是品質壓縮比
        };
    };
    reader.readAsDataURL(workingBlob);
});

window.viewSubmittedInfo = function(orderNo, amount, lastFive, imgUrl = null) {

    var lastDigits = (lastFive && lastFive !== 'None') ? lastFive : "Not provided";
    var displayAcc = lastDigits === "00000" ? "00000 (Cash Deposit)" : lastDigits;
    var infoMsg = `----------------------------
Order No: ${orderNo}
Amount Paid: $${Number(amount).toLocaleString()}
Your Account Last 5 Digits: ${displayAcc}
----------------------------
`;

    document.getElementById('modalInfo').innerText = infoMsg;

    if (imgUrl) {
        document.getElementById('modalImg').src = imgUrl;
        document.getElementById('modalImg').style.display = 'block';
    } else {
        document.getElementById('modalImg').style.display = 'none';
    }

    var modal = new bootstrap.Modal(document.getElementById('receiptModal'));
    modal.show();
}






function cancelReport(id) {
    if (!confirm("Are you sure you want to cancel?")) return;
    fetch('/cancel_transfer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({schedule_id: id})
    }).then(function(res) {
        if (res.ok) {
            alert("Cancelled!");
            location.reload();
        } else {
            alert("Failed to cancel.");
        }
    }).catch(function(err) {
        alert("Error: " + err);
    });
}

function updatePassword() {
    var p1 = document.getElementById('new_pw').value;
    var p2 = document.getElementById('confirm_pw').value;
    if (!p1 || p1.length < 6) return alert("Min 6 characters");
    if (p1 !== p2) return alert("Passwords mismatch");
    fetch('/update_password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: p1})
    }).then(function(res) {
        if (res.ok) { alert("Success!"); location.reload(); }
        else { alert("Failed"); }
    });
}

function copyAccountNumber() {
    var acc = document.getElementById('bank-account-num').innerText;
    navigator.clipboard.writeText(acc).then(function() {
        document.getElementById('copy-icon').style.display = 'none';
        document.getElementById('copy-text').style.display = 'inline';
        setTimeout(function() {
            document.getElementById('copy-icon').style.display = 'inline';
            document.getElementById('copy-text').style.display = 'none';
        }, 1500);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    var app = document.getElementById('reconcile-app');
    if (app) {
        app.addEventListener('click', function(e) {
            var btn = e.target.closest('.btn-trigger-transfer');
            if (btn) {
                document.getElementById('report_order_no').value = btn.getAttribute('data-order');
                document.getElementById('report_sid').value = btn.getAttribute('data-sid');
                document.getElementById('report_amount').value = btn.getAttribute('data-amount');
                document.getElementById('report_five').value = '';
            }
        });
    }

    var subBtn = document.getElementById('btn-submit-payment');

if (subBtn) {
    subBtn.addEventListener('click', function() {
        var schedule_id = document.getElementById('report_sid').value;
        var order_no = document.getElementById('report_order_no').value;
        var amount = document.getElementById('report_amount').value;
        var last_five = document.getElementById('report_five').value;

        if (!amount || last_five.length !== 5) return alert("Check amount or last 5 digits");

        var fd = new FormData();
        fd.append('schedule_id', schedule_id);
        fd.append('order_no', order_no);
        fd.append('amount', amount);
        fd.append('last_five', last_five);

        // 【關鍵修改】優先使用我們轉好的 finalFileToUpload
        // 如果沒有（例如沒選照片），則嘗試從 input 抓
        var fileToUse = finalFileToUpload || document.getElementById('receipt_img').files[0];
        
        if (fileToUse) {
            fd.append('receipt_img', fileToUse);
        }

        fetch('/submit_transfer', {
            method: 'POST',
            body: fd
        }).then(function(res) {
            if (res.ok) {
                alert("Success!");
                location.reload();
            } else {
                // 如果失敗，看看後端回傳什麼
                res.json().then(data => {
                    alert("Failed: " + (data.message || "Unknown error"));
                });
            }
        }).catch(err => {
            console.error("Fetch error:", err);
            alert("Network error, please try again.");
        });
    });
}
});

</script>
"""


BARCODE_PAGE = """
<div class="container py-2">
    {# --- Condition 1: If Barcode is Expired --- #}
    {% if b.is_expired %}
    <div class="card shadow border-0 p-4 text-center" style="border-radius: 20px; margin-top: 50px;">
        <div class="py-5">
            <i class="fas fa-exclamation-triangle text-danger mb-4" style="font-size: 4rem;"></i>
            <h4 class="fw-bold text-dark">Barcode Expired</h4>
            <p class="text-muted small px-3">This barcode has passed its payment deadline and is no longer valid for transaction.</p>
            
            <div class="alert alert-danger border-0 small mt-4 mx-2 fw-bold" style="border-radius: 12px; background-color: #fff5f5; color: #e53e3e;">
                <i class="fas fa-headset me-1"></i> CONTACT CUSTOMER SERVICE
            </div>

            <div class="px-3 mt-4">
                <button onclick="goBack()" class="btn btn-outline-secondary w-100 py-2 small border-0">
                    Back to Order List
                </button>
            </div>
        </div>
    </div>

    {# --- Condition 2: Normal Display --- #}
    {% else %}
    <div class="text-center mb-4">
        <p class="text-danger small fw-bold">
            <i class="fas fa-sun me-1"></i>Please turn your screen brightness to maximum and present this to the clerk.
        </p>
    </div>
    <div class="notice-box p-3 mb-4 shadow-sm" style="background-color: #f8f9fa; border-radius: 15px; border-left: 4px solid #ffc107;">
        <h6 class="fw-bold text-dark mb-2"><i class="fas fa-info-circle text-warning me-1"></i> Payment Notice</h6>
        <ul class="small text-muted mb-0 ps-3">
            <li class="mb-2">After payment, please <b>take a photo of the receipt</b> and send to our <b>LINE</b>.</li>
            <li class="mb-2 text-danger">Verification takes <b>5 to 7 working days</b>.</li>
            <li>Status will <b>automatically update</b>. Thank you!</li>
        </ul>
    </div>
    <div class="card mb-3 border-0 shadow-sm" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 15px;">
        <div class="card-body text-center text-white py-3">
            <div class="small opacity-75">Total Amount</div>
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



    <div class="px-2 mb-5">
        <button onclick="goBack()" class="btn btn-outline-primary w-100 py-3 fw-bold rounded-3 shadow-sm">
            <i class="fas fa-arrow-left me-2"></i>Back to Order List
        </button>
    </div>
    {% endif %}
</div>

<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>
<script>
    {# Render barcodes only if NOT expired #}
    {% if not b.is_expired %}
    const opt = { format: "CODE39", width: 1, height: 60, displayValue: false, margin: 10 };
    JsBarcode("#barcode1", "{{ b.barcode_1 }}", opt);
    JsBarcode("#barcode2", "{{ b.barcode_2 }}", opt);
    JsBarcode("#barcode3", "{{ b.barcode_3 }}", opt);
    {% endif %}

    function goBack() {
        // Redirect with timestamp to force dashboard refresh
        window.location.href = '/dashboard?t=' + new Date().getTime();
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
        now = datetime.now()
        for order in orders:
            for s in order.get('payment_schedule', []):
                s['last_five'] = s.get('last_five', '')
                # 1. 檢查是否已經有條碼資料 (排除空值、None 或字串 '0')
                has_existing_code = bool(s.get('barcode_1') and s.get('barcode_1') != '0') or \
                                    bool(s.get('has_barcode') and s.get('has_barcode') != '0')

                if s.get('date'):
                    try:
                        # 轉換日期字串為 datetime 物件
                        due_date = datetime.strptime(s['date'][:10], '%Y-%m-%d')
                        # 計算開放日期 (截止前 20 天)
                        open_date = due_date - timedelta(days=20)
                        
                        # 邏輯：(現在時間到了) OR (已經有條碼了) 都要開放按鈕
                        s['is_open'] = (now >= open_date) or has_existing_code
                        s['open_date_str'] = open_date.strftime('%Y-%m-%d')
                    except:
                        s['is_open'] = has_existing_code
                        s['open_date_str'] = 'Pending'
                else:
                    # 沒有日期時，僅依據是否有條碼來決定是否開放
                    s['is_open'] = has_existing_code
                    s['open_date_str'] = 'Pending'
        # -----------------------
        
        # 存入 session 備用（供 get_barcode 檢查用）
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

        # 20天開放期攔截邏輯
        if payment_info and payment_info.get('date'):
            try:
                due_date = datetime.strptime(payment_info['date'][:10], '%Y-%m-%d')
                open_date = due_date - timedelta(days=20)
                if datetime.now() < open_date and not (payment_info.get('has_barcode') or payment_info.get('barcode_1')):
                    return f"Available after: {open_date.strftime('%Y-%m-%d')}"
            except Exception as date_e:
                print(f"Date check error: {date_e}")

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
        print(f"DEBUG - Laravel Response: {data}")
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
        # 1. 取得速買配傳過來的 POST 資料 (這會包含 Smseid, Amount, 等參數)
        #raw_data = request.form.to_dict()
        form_data = request.form.to_dict()
        values_data = request.values.to_dict()
        raw_body = request.get_data() # 這是最後的殺手鐧

        print("--- [DEBUG] Raw Body ---", flush=True)
        print(raw_body, flush=True) # 如果這裡有印出字，代表資料有進來

        # 💡 2. 整合資料
        raw_data = form_data or values_data
        
        # 💡 3. 如果 form_data 是空的但 raw_body 有東西，手動解析
        if not raw_data and raw_body:
            from urllib.parse import parse_qs
            raw_data = {k: v[0] for k, v in parse_qs(raw_body.decode('utf-8')).items()}

        print("--- [DEBUG] Final Processed Data ---", flush=True)
        print(raw_data, flush=True)
        if not raw_data:
            return "No data received", 400
            
       
        if 'SmilePayNO' in raw_data or 'Smseid' in raw_data:
            php_callback_url = f"{PHP_API_URL}/payment/callback/smilepay"      
        elif 'CheckMacValue' in raw_data:   
            php_callback_url = f"{PHP_API_URL}/payment/callback/ecpay"
        else:
            print(f"Unknown provider data: {raw_data}")
            return "Unknown provider", 400
            
            
        # 使用 requests 發送 POST
        php_response = requests.post(
            php_callback_url, 
            data=raw_data, 
            timeout=10 # 設定超時避免卡死
        )
        
        # PHP 那邊會回傳 "1|OK" 或 "0|BarcodeNotFound" 等字串
        if php_response.status_code == 200:
            if "1|OK" in php_response.text:
                from flask import Response
                return Response("1|OK", mimetype='text/plain')
            else:
                # 如果 PHP 回傳的是 0|Error 或其他訊息
                print(f"PHP Logic Error: {php_response.text}")
                return f"PHP processing failed: {php_response.text}", 200 
                # 注意：這裡回傳 200 但內容不是標籤，SmilePay 就會視為失敗並補傳
        else:
            # 如果 PHP 噴錯 (500 等)，回報給 Python Log
            print(f"PHP API Error: {php_response.status_code} - {php_response.text}")
            return f"Backend Error: {php_response.status_code}", 500
            
    except Exception as e:
        print(f"Proxy Critical Error: {str(e)}")
        return "Internal Proxy Error", 500
        
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