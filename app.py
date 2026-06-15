import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from datetime import date, datetime, timedelta
from pathlib import Path

APP_NAME = "AYÇA Borç Takip"
DB_PATH = Path("ayca_borc_takip.db")

# ----------------------------
# SETTINGS
# ----------------------------
DEFAULT_DEBT_LIMIT = 3000  # TL
OVERDUE_WARNING_DAYS = 0   # Vade geçince direkt gecikmiş sayılır

USERS = {
    # Şifreleri ilk giriş sonrası değiştirmek istersen aşağıdaki değerleri güncelleriz.
    # Kullanıcı adı: sifre
    "admin": "1234",
    "kalfa": "1234",
}

# ----------------------------
# HELPERS
# ----------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def check_login(username: str, password: str) -> bool:
    if username not in USERS:
        return False
    return hash_password(password) == hash_password(USERS[username])

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

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

def add_customer(full_name, phone, note):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO customers (full_name, phone, note, created_at) VALUES (?, ?, ?, ?)",
        (full_name.strip(), phone.strip(), note.strip(), datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()

def add_transaction(customer_id, tx_type, amount, description, due_date, created_by):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO debt_transactions 
        (customer_id, tx_type, amount, description, due_date, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        customer_id,
        tx_type,
        float(amount),
        description.strip(),
        due_date.isoformat() if due_date else None,
        created_by,
        datetime.now().isoformat(timespec="seconds")
    ))
    conn.commit()
    conn.close()

def load_customers():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM customers ORDER BY full_name", conn)
    conn.close()
    return df

def load_transactions():
    conn = get_conn()
    query = """
    SELECT 
        t.id,
        t.customer_id,
        c.full_name,
        c.phone,
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

    today = date.today()

    def status(row):
        if row["toplam_borc"] <= 0:
            return "Borç yok"
        if row["toplam_borc"] >= DEFAULT_DEBT_LIMIT:
            return "Limit aşıldı"
        if row["en_eski_vade"]:
            try:
                d = datetime.fromisoformat(row["en_eski_vade"]).date()
                if d < today - timedelta(days=OVERDUE_WARNING_DAYS):
                    return "Vadesi geçti"
            except Exception:
                pass
        return "Aktif borç"

    df["durum"] = df.apply(status, axis=1)

    return df[[
        "id", "full_name", "phone", "toplam_borc", "en_eski_vade",
        "durum", "son_islem", "note"
    ]]

def money(x):
    return f"{x:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")

# ----------------------------
# APP
# ----------------------------
st.set_page_config(page_title=APP_NAME, page_icon="💊", layout="wide")
init_db()

st.title("💊 AYÇA Borç Takip")
st.caption("İdil Eczanesi için müşteri borç ve tahsilat takip sistemi")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.subheader("Giriş")
    with st.form("login_form"):
        username = st.text_input("Kullanıcı adı")
        password = st.text_input("Şifre", type="password")
        submitted = st.form_submit_button("Giriş Yap")

    if submitted:
        if check_login(username, password):
            st.session_state.logged_in = True
            st.session_state.username = username
            st.rerun()
        else:
            st.error("Kullanıcı adı veya şifre hatalı.")
    st.stop()

with st.sidebar:
    st.success(f"Giriş yapan: {st.session_state.username}")
    st.info(f"Müşteri borç limiti: {money(DEFAULT_DEBT_LIMIT)}")
    if st.button("Çıkış"):
        st.session_state.logged_in = False
        st.rerun()

tab_dashboard, tab_customer, tab_debt, tab_payment, tab_history = st.tabs([
    "📊 Genel Durum", "👤 Müşteri Ekle", "➕ Borç Ekle", "✅ Ödeme Al", "📚 İşlem Geçmişi"
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
        search = st.text_input("Müşteri ara", placeholder="Ad, soyad veya telefon")
        shown = summary.copy()

        if search:
            mask = (
                shown["full_name"].str.contains(search, case=False, na=False) |
                shown["phone"].str.contains(search, case=False, na=False)
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
                "en_eski_vade": "En Eski Vade",
                "durum": "Durum",
                "son_islem": "Son İşlem",
                "note": "Not"
            }
        )

        csv = shown.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Excel/CSV olarak indir",
            data=csv,
            file_name="ayca_borc_takip_ozet.csv",
            mime="text/csv"
        )

with tab_customer:
    st.subheader("Yeni Müşteri Ekle")
    with st.form("customer_form"):
        full_name = st.text_input("Ad Soyad")
        phone = st.text_input("Telefon")
        note = st.text_area("Not", placeholder="Örn: Mahalle, yakınlık, özel not")
        submitted = st.form_submit_button("Müşteriyi Kaydet")

    if submitted:
        if not full_name.strip():
            st.error("Ad Soyad zorunludur.")
        else:
            add_customer(full_name, phone, note)
            st.success("Müşteri kaydedildi.")

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
            submitted = st.form_submit_button("Borç Ekle")

        if submitted:
            customer_id = customer_map[selected]
            current_summary = customer_summary()
            current_debt = current_summary.loc[current_summary["id"] == customer_id, "toplam_borc"]
            current_debt = float(current_debt.iloc[0]) if not current_debt.empty else 0
            new_total = current_debt + amount

            if amount <= 0:
                st.error("Tutar 0'dan büyük olmalı.")
            else:
                add_transaction(customer_id, "BORC", amount, description, due_date, st.session_state.username)
                if new_total >= DEFAULT_DEBT_LIMIT:
                    st.warning(f"Borç eklendi fakat müşteri limiti aştı: {money(new_total)}")
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
            submitted = st.form_submit_button("Ödemeyi Kaydet")

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
            shown = shown[
                shown["full_name"].str.contains(customer_filter, case=False, na=False) |
                shown["phone"].str.contains(customer_filter, case=False, na=False)
            ]

        shown["islem"] = shown["tx_type"].map({"BORC": "Borç", "ODEME": "Ödeme"})
        shown = shown[[
            "created_at", "full_name", "phone", "islem", "amount",
            "description", "due_date", "created_by"
        ]]

        st.dataframe(
            shown,
            use_container_width=True,
            hide_index=True,
            column_config={
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
