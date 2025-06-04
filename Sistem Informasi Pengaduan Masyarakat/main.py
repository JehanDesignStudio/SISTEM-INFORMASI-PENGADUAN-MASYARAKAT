from flask import Flask, render_template, request, redirect, session, url_for, make_response, render_template_string
import MySQLdb
from datetime import datetime
from io import BytesIO
import smtplib
from email.mime.text import MIMEText
import openpyxl
from xhtml2pdf import pisa

app = Flask(__name__)
app.secret_key = 'secret-key'

# Email config
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_ADDRESS = 'your_email@gmail.com'
EMAIL_PASSWORD = 'your_app_password'

# DB Connection
db = MySQLdb.connect(host="localhost", user="root", passwd="", db="pengaduan_db")
cursor = db.cursor()

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cursor.fetchone()
        if user:
            session['user_id'] = user[0]
            session['role'] = user[4]  # Kolom ke-5 = role

            if user[4] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user[4] == 'pengunjung':
                return redirect(url_for('pengunjung_dashboard'))
            else:
                return 'Role tidak dikenali'
        else:
            return 'Login gagal. Username atau password salah.'
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = 'pengunjung'
        cursor.execute("INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)",
                       (username, email, password, role))
        db.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

# -------------------- PENGUNJUNG --------------------
@app.route('/pengaduan', methods=['GET', 'POST'])
def form_pengaduan():
    if 'user_id' not in session or session['role'] != 'pengunjung':
        return redirect(url_for('login'))
    if request.method == 'POST':
        nama = request.form['nama']
        kategori = request.form['kategori']
        deskripsi = request.form['deskripsi']
        cursor.execute("INSERT INTO pengaduan (nama, kategori, deskripsi, user_id) VALUES (%s, %s, %s, %s)",
                       (nama, kategori, deskripsi, session['user_id']))
        db.commit()
        return redirect(url_for('daftar_pengaduan'))
    return render_template('pengunjung/form_pengaduan.html')

@app.route('/pengunjung/dashboard')
def pengunjung_dashboard():
    if 'user_id' not in session or session['role'] != 'pengunjung':
        return redirect(url_for('login'))
    return render_template('pengunjung/dashboard.html')

@app.route('/pengaduan/daftar')
def daftar_pengaduan():
    if 'user_id' not in session or session['role'] != 'pengunjung':
        return redirect(url_for('login'))

    cursor.execute("SELECT * FROM pengaduan WHERE user_id=%s", (session['user_id'],))
    data = cursor.fetchall()
    cursor.execute("UPDATE pengaduan SET notifikasi=FALSE WHERE user_id=%s", (session['user_id'],))
    db.commit()
    return render_template('pengunjung/daftar_pengaduan.html', pengaduan=data)

@app.route('/pengaduan/log/<int:pengaduan_id>')
def riwayat_status(pengaduan_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    cursor.execute("SELECT status_baru, tanggal FROM status_log WHERE pengaduan_id = %s ORDER BY tanggal DESC", (pengaduan_id,))
    logs = cursor.fetchall()
    return render_template('pengunjung/status_log.html', logs=logs)

# -------------------- ADMIN --------------------
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    cursor.execute("SELECT * FROM pengaduan")
    data = cursor.fetchall()
    return render_template('admin/dashboard.html', pengaduan=data)

@app.route('/admin/update_status/<int:pengaduan_id>', methods=['POST'])
def update_status(pengaduan_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    status_baru = request.form['status']
    cursor.execute("SELECT user_id FROM pengaduan WHERE id = %s", (pengaduan_id,))
    user_id = cursor.fetchone()[0]
    cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
    email_user = cursor.fetchone()[0]

    cursor.execute("UPDATE pengaduan SET status = %s, notifikasi = TRUE WHERE id = %s", (status_baru, pengaduan_id))
    cursor.execute("INSERT INTO status_log (pengaduan_id, status_baru) VALUES (%s, %s)", (pengaduan_id, status_baru))
    db.commit()

    kirim_email(email_user, "Status Pengaduan Anda Diperbarui",
                f"Status pengaduan Anda telah diperbarui menjadi: {status_baru}")
    return redirect(url_for('admin_dashboard'))

# -------------------- TOOLS --------------------
def kirim_email(penerima, subjek, pesan):
    msg = MIMEText(pesan)
    msg['Subject'] = subjek
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = penerima
    try:
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, [penerima], msg.as_string())
        server.quit()
    except Exception as e:
        print("Gagal kirim email:", e)

@app.route('/admin/export_pdf')
def export_pdf():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    status_filter = request.args.get('status')
    if status_filter:
        cursor.execute("SELECT nama, kategori, deskripsi, status, created_at FROM pengaduan WHERE status=%s", (status_filter,))
    else:
        cursor.execute("SELECT nama, kategori, deskripsi, status, created_at FROM pengaduan")
    data = cursor.fetchall()

    html = render_template_string("""
    <html><head><style>
        table { width: 100%; border-collapse: collapse; }
        th, td { border: 1px solid black; padding: 6px; font-size: 12px; }
    </style></head><body>
        <h3>Export Pengaduan {% if status %}Status: {{ status }}{% else %}Semua{% endif %}</h3>
        <table>
            <tr><th>Nama</th><th>Kategori</th><th>Deskripsi</th><th>Status</th><th>Tanggal</th></tr>
            {% for row in data %}
            <tr>
                <td>{{ row[0] }}</td>
                <td>{{ row[1] }}</td>
                <td>{{ row[2] }}</td>
                <td>{{ row[3] }}</td>
                <td>{{ row[4] }}</td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """, data=data, status=status_filter)

    pdf = BytesIO()
    pisa.CreatePDF(html, dest=pdf)
    pdf.seek(0)

    response = make_response(pdf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=pengaduan.pdf'
    return response

@app.route('/admin/export_excel')
def export_excel():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    status_filter = request.args.get('status')
    if status_filter:
        cursor.execute("SELECT nama, kategori, deskripsi, status, created_at FROM pengaduan WHERE status=%s", (status_filter,))
    else:
        cursor.execute("SELECT nama, kategori, deskripsi, status, created_at FROM pengaduan")
    data = cursor.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pengaduan"
    headers = ["Nama", "Kategori", "Deskripsi", "Status", "Tanggal"]
    ws.append(headers)
    for row in data:
        ws.append(row)

    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    response = make_response(excel_file.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = 'attachment; filename=pengaduan.xlsx'
    return response

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
