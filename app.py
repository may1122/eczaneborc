import streamlit as st
import sqlite3
import hashlib
import pandas as pd
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

APP_NAME = "AYÇA Borç Takip"
DB_PATH = Path("ayca_borc_takip.db")

DEFAULT_DEBT_LIMIT = 3000
OVERDUE_WARNING_DAYS = 0

USERS = {
    "admin": {"password": "1234", "role": "admin"},
    "kalfa": {"password": "1234", "role": "staff"},
}

st.set_page_config(page_title=APP_NAME, page_icon="💊", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.3rem;}
.ayca-header {
    padding: 22px 26px;
    border-radius: 22px;
    background: linear-gradient(135deg, #0f766e 0%, #14b8a6 48%, #67e8f9 100%);
    color: white;
    margin-bottom: 18px;
    box-shadow: 0 10px 28px rgba(15, 118, 110, 0.20);
}
.ayca-header h1 {margin: 0; font-size: 34px; font-weight: 800;}
.ayca-header p {margin: 6px 0 0 0; font-size: 15px; opacity: 0.95;}
.alert-card {
    padding: 18px;
    border-radius: 18px;
    background: white;
    border: 1px solid #e5e7eb;
    box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
    margin-bottom: 12px;
}
.alert-limit {border-left: 7px solid #dc2626;}
.alert-overdue {border-left: 7px solid #f97316;}
.alert-normal {border-left: 7px solid #0f766e;}
.card-name {font-size: 19px; font-weight: 800; color: #111827;}
.card-debt {font-size: 25px; font-weight: 900; color: #dc2626;}
.card-small {color: #6b7280; font-size: 13px;}
.badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    margin-top: 8px;
}
.badge-red {background: #fee2e2; color: #991b1b;}
.badge-orange {background: #ffedd5; color: #9a3412;}
.badge-green {background: #dcfce7; color: #166534;}
</style>
""", unsafe_allow_html=True)


def normalize_name(name: str) -> str:
    if not name:
        return ""
    text = name.strip().lower()
    tr_map = str.maketrans({
        "ı": "i", "İ": "i", "ğ": "g", "ü": "u",
        "ş": "s", "ö": "o", "ç": "c"
    })
    text = text.translate(tr_map)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = " ".join(text.split())
    return text


def title_name(name: str) -> str:
    return " ".join([p.capitalize() for p in name.strip().split()])


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def check_login(username: str, password: str) -> bool:
    username = username.strip().lower()
    if username not in USERS:
        return False
    return hash_password(password) == hash_password(USERS[username]["password"])


def get_user_role(username: str) -> str:
    return USERS.get(username, {}).get("role", "staff")


def is_admin() -> bool:
    return st.session_state.get("role") == "admin"


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(table_name, column_name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = [row["name"] for row in cur.fetchall()]
    conn.close()
    return column_name in cols


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        phone TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS debt_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        tx_type TEXT NOT NULL CHECK(tx_type IN ('BORC', 'ODEME')),
        amount REAL NOT NULL,
        description TEXT,
        due_date TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    )
    """)

    conn.commit()
    conn.close()

    if not column_exists("customers", "normalized_name"):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("ALTER TABLE customers ADD COLUMN normalized_name TEXT")
        conn.commit()
        conn.close()

    if not column_exists("customers", "debt_limit"):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"ALTER TABLE customers ADD COLUMN debt_limit REAL DEFAULT {DEFAULT_DEBT_LIMIT}")
        conn.commit()
        conn.close()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name FROM customers WHERE normalized_name IS NULL OR normalized_name = ''")
    rows = cur.fetchall()
    for row in rows:
        cur.execute(
            "UPDATE customers SET normalized_name = ? WHERE id = ?",
            (normalize_name(row["full_name"]), row["id"])
        )
    conn.commit()
    conn.close()


def add_customer(full_name, phone, note, debt_limit):
    normalized = normalize_name(full_name)
    clean_name = title_name(full_name)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name FROM customers WHERE normalized_name = ?", (normalized,))
    existing = cur.fetchone()

    if existing:
        conn.close()
        return False, existing["full_name"]

    cur.execute("""
        INSERT INTO customers 
        (full_name, normalized_name, phone, note, debt_limit, created_at) 
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        clean_name,
        normalized,
        phone.strip(),
        note.strip(),
        float(debt_limit),
        datetime.now().isoformat(timespec="seconds")
    ))
    conn.commit()
    conn.close()
    return True, clean_name


def add_transaction(customer_id, tx_type, amount, description, due_date, created_by):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO debt_transactions 
        (customer_id, tx_type, amount, description, due_date, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        int(customer_id),
        tx_type,
        float(amount),
        description.strip(),
        due_date.isoformat() if due_date else None,
        created_by,
        datetime.now().isoformat(timespec="seconds")
    ))
    conn.commit()
    conn.close()


def delete_transaction(tx_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM debt_transactions WHERE id = ?", (int(tx_id),))
    conn.commit()
    conn.close()


def delete_customer(customer_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM debt_transactions WHERE customer_id = ?", (int(customer_id),))
    cur.execute("DELETE FROM customers WHERE id = ?", (int(customer_id),))
    conn.commit()
    conn.close()


def load_customers():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM customers ORDER BY full_name", conn)
    conn.close()

    if not df.empty:
        if "debt_limit" not in df.columns:
            df["debt_limit"] = DEFAULT_DEBT_LIMIT
        df["debt_limit"] = df["debt_limit"].fillna(DEFAULT_DEBT_LIMIT)

    return df


def load_transactions():
    conn = get_conn()
    query = """
    SELECT 
        t.id,
        t.customer_id,
        c.full_name,
        c.phone,
        c.debt_limit,
        t.tx_type,
        t.amount,
        t.description,
        t.due_date,
        t.created_by,
        t.created_at
    FROM debt_transactions t
    JOIN customers c ON c.id = t.customer_id
    ORDER BY t.created_at DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def customer_summary():
    customers = load_customers()
    tx = load_transactions()

    if customers.empty:
        return pd.DataFrame()

    if tx.empty:
        customers["toplam_borc"] = 0.0
        customers["son_islem"] = ""
        customers["en_eski_vade"] = ""
        customers["geciken_gun"] = 0
        customers["durum"] = "Borç yok"
        return customers

    tx["signed_amount"] = tx.apply(
        lambda r: r["amount"] if r["tx_type"] == "BORC" else -r["amount"], axis=1
    )

    balances = tx.groupby("customer_id", as_index=False)["signed_amount"].sum()
    balances = balances.rename(columns={"signed_amount": "toplam_borc"})

    last_tx = tx.groupby("customer_id", as_index=False)["created_at"].max()
    last_tx = last_tx.rename(columns={"created_at": "son_islem"})

    unpaid_due = tx[(tx["tx_type"] == "BORC") & (tx["due_date"].notna())].copy()

    if not unpaid_due.empty:
        unpaid_due["due_date_dt"] = pd.to_datetime(unpaid_due["due_date"], errors="coerce")
        oldest_due = unpaid_due.groupby("customer_id", as_index=False)["due_date_dt"].min()
        oldest_due["en_eski_vade"] = oldest_due["due_date_dt"].dt.date.astype(str)
        oldest_due = oldest_due[["customer_id", "en_eski_vade"]]
    else:
        oldest_due = pd.DataFrame(columns=["customer_id", "en_eski_vade"])

    df = customers.merge(balances, left_on="id", right_on="customer_id", how="left")
    df = df.merge(last_tx, left_on="id", right_on="customer_id", how="left", suffixes=("", "_last"))
    df = df.merge(oldest_due, left_on="id", right_on="customer_id", how="left", suffixes=("", "_due"))

    df["toplam_borc"] = df["toplam_borc"].fillna(0).round(2)
    df["son_islem"] = df["son_islem"].fillna("")
    df["en_eski_vade"] = df["en_eski_vade"].fillna("")
    df["debt_limit"] = df["debt_limit"].fillna(DEFAULT_DEBT_LIMIT)

    today = date.today()

    def overdue_days(vade):
        if not vade:
            return 0
        try:
            d = datetime.fromisoformat(str(vade)).date()
            return max((today - d).days, 0)
        except Exception:
            return 0

    df["geciken_gun"] = df["en_eski_vade"].apply(overdue_days)

    def status(row):
        if row["toplam_borc"] <= 0:
            return "Borç yok"
        if row["toplam_borc"] >= row["debt_limit"]:
            return "Limit aşıldı"
        if row["geciken_gun"] > OVERDUE_WARNING_DAYS:
            return "Vadesi geçti"
        return "Aktif borç"

    df["durum"] = df.apply(status, axis=1)

    return df[[
        "id", "full_name", "phone", "toplam_borc", "debt_limit",
        "en_eski_vade", "geciken_gun", "durum", "son_islem", "note"
    ]]


def money(x):
    try:
        return f"{float(x):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00 TL"


def render_customer_card(row, card_type="normal"):
    cls = "alert-card alert-normal"
    badge = "badge badge-green"
    if card_type == "limit":
        cls = "alert-card alert-limit"
        badge = "badge badge-red"
    elif card_type == "overdue":
        cls = "alert-card alert-overdue"
        badge = "badge badge-orange"

    phone = row.get("phone", "") or "Telefon yok"
    vade = row.get("en_eski_vade", "") or "-"
    geciken = int(row.get("geciken_gun", 0) or 0)
    limit = row.get("debt_limit", DEFAULT_DEBT_LIMIT)

    st.markdown(f"""
    <div class="{cls}">
        <div class="card-name">{row["full_name"]}</div>
        <div class="card-debt">{money(row["toplam_borc"])}</div>
        <div class="card-small">Telefon: {phone}</div>
        <div class="card-small">Limit: {money(limit)} | En eski vade: {vade} | Geciken gün: {geciken}</div>
        <span class="{badge}">{row["durum"]}</span>
    </div>
    """, unsafe_allow_html=True)


init_db()

st.markdown("""
<div class="ayca-header">
    <h1>💊 AYÇA Borç Takip</h1>
    <p>İdil Eczanesi için müşteri borç, vade, limit ve tahsilat takip paneli</p>
</div>
""", unsafe_allow_html=True)

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.subheader("Giriş")
        with st.form("login_form"):
            username = st.text_input("Kullanıcı adı")
            password = st.text_input("Şifre", type="password")
            submitted = st.form_submit_button("Giriş Yap", use_container_width=True)

        if submitted:
            clean_username = username.strip().lower()
            if check_login(clean_username, password):
                st.session_state.logged_in = True
                st.session_state.username = clean_username
                st.session_state.role = get_user_role(clean_username)
                st.rerun()
            else:
                st.error("Kullanıcı adı veya şifre hatalı.")
    st.stop()

with st.sidebar:
    st.success(f"Giriş yapan: {st.session_state.username}")
    st.caption("Yetki: Yönetici" if is_admin() else "Yetki: Kalfa")
    if is_admin():
        st.warning("Silme işlemleri sadece yönetici hesabında açıktır.")
    else:
        st.info("Kalfa hesabı kayıt ekleyebilir ve ödeme alabilir; silemez.")
    if st.button("Çıkış", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.rerun()

tab_dashboard, tab_customer, tab_debt, tab_payment, tab_history, tab_admin = st.tabs([
    "📊 Genel Durum", "👤 Müşteri Ekle", "➕ Borç Ekle", "✅ Ödeme Al", "📚 İşlem Geçmişi", "⚙️ Yönetici"
])

with tab_dashboard:
    summary = customer_summary()

    total_debt = summary["toplam_borc"].sum() if not summary.empty else 0
    overdue_count = len(summary[summary["durum"] == "Vadesi geçti"]) if not summary.empty else 0
    limit_count = len(summary[summary["durum"] == "Limit aşıldı"]) if not summary.empty else 0
    active_count = len(summary[summary["toplam_borc"] > 0]) if not summary.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Borç", money(total_debt))
    c2.metric("Borçlu Müşteri", active_count)
    c3.metric("Vadesi Geçen", overdue_count)
    c4.metric("Limit Aşan", limit_count)

    st.divider()

    if summary.empty:
        st.warning("Henüz müşteri kaydı yok.")
    else:
        limit_df = summary[summary["durum"] == "Limit aşıldı"].sort_values("toplam_borc", ascending=False)
        overdue_df = summary[summary["durum"] == "Vadesi geçti"].sort_values("geciken_gun", ascending=False)

        if not limit_df.empty:
            st.subheader("🚨 Limiti Aşan Müşteriler")
            cols = st.columns(3)
            for i, (_, row) in enumerate(limit_df.iterrows()):
                with cols[i % 3]:
                    render_customer_card(row, "limit")

        if not overdue_df.empty:
            st.subheader("⏰ Vadesi Geçen Müşteriler")
            cols = st.columns(3)
            for i, (_, row) in enumerate(overdue_df.iterrows()):
                with cols[i % 3]:
                    render_customer_card(row, "overdue")

        st.subheader("📋 Tüm Müşteriler")
        search = st.text_input("Müşteri ara", placeholder="Ad, soyad veya telefon")

        shown = summary.copy()
        if search:
            normalized_search = normalize_name(search)
            mask = (
                shown["full_name"].apply(normalize_name).str.contains(normalized_search, case=False, na=False) |
                shown["phone"].astype(str).str.contains(search, case=False, na=False)
            )
            shown = shown[mask]

        st.dataframe(
            shown.sort_values(["toplam_borc"], ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": "ID",
                "full_name": "Müşteri",
                "phone": "Telefon",
                "toplam_borc": st.column_config.NumberColumn("Toplam Borç", format="%.2f TL"),
                "debt_limit": st.column_config.NumberColumn("Limit", format="%.2f TL"),
                "en_eski_vade": "En Eski Vade",
                "geciken_gun": "Geciken Gün",
                "durum": "Durum",
                "son_islem": "Son İşlem",
                "note": "Not"
            }
        )

        csv = shown.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "CSV olarak indir",
            data=csv,
            file_name="ayca_borc_takip_ozet.csv",
            mime="text/csv"
        )

with tab_customer:
    st.subheader("Yeni Müşteri Ekle")
    st.caption("Aynı kişi farklı yazımla girilirse sistem tekrar kayıt açmaz. Örn: İdil YILMAZ = İDİL YILMAZ = idil yılmaz")

    with st.form("customer_form"):
        full_name = st.text_input("Ad Soyad")
        phone = st.text_input("Telefon")
        debt_limit = st.number_input("Müşteri Borç Limiti", min_value=0.0, value=float(DEFAULT_DEBT_LIMIT), step=250.0)
        note = st.text_area("Not", placeholder="Örn: Mahalle, yakınlık, özel not")
        submitted = st.form_submit_button("Müşteriyi Kaydet", use_container_width=True)

    if submitted:
        if not full_name.strip():
            st.error("Ad Soyad zorunludur.")
        else:
            ok, result_name = add_customer(full_name, phone, note, debt_limit)
            if ok:
                st.success(f"{result_name} müşterisi kaydedildi.")
            else:
                st.warning(f"Bu kişi zaten kayıtlı görünüyor: {result_name}")

with tab_debt:
    st.subheader("Borç Ekle")
    customers = load_customers()

    if customers.empty:
        st.warning("Önce müşteri eklemelisin.")
    else:
        customer_map = {
            f"{row['full_name']} - {row['phone'] or 'Telefon yok'}": row["id"]
            for _, row in customers.iterrows()
        }

        with st.form("debt_form"):
            selected = st.selectbox("Müşteri", list(customer_map.keys()))
            amount = st.number_input("Borç Tutarı", min_value=0.0, step=10.0)
            description = st.text_input("Açıklama", placeholder="Örn: İlaç, bebek ürünü, takviye vb.")
            due_date = st.date_input("Vade Tarihi", value=date.today() + timedelta(days=30))
            submitted = st.form_submit_button("Borç Ekle", use_container_width=True)

        if submitted:
            customer_id = customer_map[selected]
            current_summary = customer_summary()
            current_row = current_summary[current_summary["id"] == customer_id]

            current_debt = float(current_row["toplam_borc"].iloc[0]) if not current_row.empty else 0
            limit = float(current_row["debt_limit"].iloc[0]) if not current_row.empty else DEFAULT_DEBT_LIMIT
            new_total = current_debt + amount

            if amount <= 0:
                st.error("Tutar 0'dan büyük olmalı.")
            else:
                add_transaction(customer_id, "BORC", amount, description, due_date, st.session_state.username)
                if new_total >= limit:
                    st.warning(f"Borç eklendi fakat müşteri limitini aştı: {money(new_total)} / Limit: {money(limit)}")
                else:
                    st.success(f"Borç eklendi. Yeni toplam: {money(new_total)}")

with tab_payment:
    st.subheader("Ödeme Al")
    summary = customer_summary()
    debtors = summary[summary["toplam_borc"] > 0] if not summary.empty else pd.DataFrame()

    if debtors.empty:
        st.info("Aktif borçlu müşteri yok.")
    else:
        customer_map = {
            f"{row['full_name']} - Borç: {money(row['toplam_borc'])}": row["id"]
            for _, row in debtors.iterrows()
        }

        with st.form("payment_form"):
            selected = st.selectbox("Borçlu Müşteri", list(customer_map.keys()))
            amount = st.number_input("Ödeme Tutarı", min_value=0.0, step=10.0)
            description = st.text_input("Açıklama", value="Tahsilat")
            submitted = st.form_submit_button("Ödemeyi Kaydet", use_container_width=True)

        if submitted:
            customer_id = customer_map[selected]
            if amount <= 0:
                st.error("Tutar 0'dan büyük olmalı.")
            else:
                add_transaction(customer_id, "ODEME", amount, description, None, st.session_state.username)
                st.success("Ödeme kaydedildi.")

with tab_history:
    st.subheader("İşlem Geçmişi")
    tx = load_transactions()

    if tx.empty:
        st.info("Henüz işlem yok.")
    else:
        customer_filter = st.text_input("Geçmişte müşteri ara")
        shown = tx.copy()

        if customer_filter:
            normalized_filter = normalize_name(customer_filter)
            shown = shown[
                shown["full_name"].apply(normalize_name).str.contains(normalized_filter, case=False, na=False) |
                shown["phone"].astype(str).str.contains(customer_filter, case=False, na=False)
            ]

        shown["islem"] = shown["tx_type"].map({"BORC": "Borç", "ODEME": "Ödeme"})
        display_df = shown[[
            "id", "created_at", "full_name", "phone", "islem", "amount",
            "description", "due_date", "created_by"
        ]]

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": "İşlem ID",
                "created_at": "Kayıt Tarihi",
                "full_name": "Müşteri",
                "phone": "Telefon",
                "islem": "İşlem",
                "amount": st.column_config.NumberColumn("Tutar", format="%.2f TL"),
                "description": "Açıklama",
                "due_date": "Vade",
                "created_by": "Kaydeden"
            }
        )

with tab_admin:
    st.subheader("Yönetici Paneli")

    if not is_admin():
        st.error("Bu alan sadece yönetici hesabında açıktır.")
    else:
        st.warning("Dikkat: Silme işlemi geri alınamaz.")

        admin_action = st.radio(
            "İşlem seç",
            ["Müşteri sil", "Tek işlem sil"],
            horizontal=True
        )

        if admin_action == "Müşteri sil":
            summary = customer_summary()
            if summary.empty:
                st.info("Silinecek müşteri yok.")
            else:
                customer_map = {
                    f"{row['full_name']} - Borç: {money(row['toplam_borc'])}": row["id"]
                    for _, row in summary.iterrows()
                }

                selected = st.selectbox("Silinecek müşteri", list(customer_map.keys()))
                confirm = st.checkbox("Bu müşteriyi ve tüm borç/ödeme geçmişini silmeyi onaylıyorum.")

                if st.button("Müşteriyi Kalıcı Olarak Sil", type="primary", use_container_width=True):
                    if not confirm:
                        st.error("Silmek için onay kutusunu işaretlemelisin.")
                    else:
                        delete_customer(customer_map[selected])
                        st.success("Müşteri ve tüm işlem geçmişi silindi.")
                        st.rerun()

        if admin_action == "Tek işlem sil":
            tx = load_transactions()
            if tx.empty:
                st.info("Silinecek işlem yok.")
            else:
                tx["islem"] = tx["tx_type"].map({"BORC": "Borç", "ODEME": "Ödeme"})
                tx["label"] = tx.apply(
                    lambda r: f"ID {r['id']} - {r['full_name']} - {r['islem']} - {money(r['amount'])} - {r['created_at']}",
                    axis=1
                )
                selected = st.selectbox("Silinecek işlem", tx["label"].tolist())
                selected_id = int(tx.loc[tx["label"] == selected, "id"].iloc[0])
                confirm = st.checkbox("Bu tek işlemi silmeyi onaylıyorum.")

                if st.button("İşlemi Kalıcı Olarak Sil", type="primary", use_container_width=True):
                    if not confirm:
                        st.error("Silmek için onay kutusunu işaretlemelisin.")
                    else:
                        delete_transaction(selected_id)
                        st.success("İşlem silindi.")
                        st.rerun()
