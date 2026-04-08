import os
import io
import json
import re
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# ========= 基础路径 =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
PASSWORD_FILE = os.path.join(DATA_DIR, "passwords.json")
INDEX_FILE = os.path.join(DATA_DIR, "archive_index.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

st.set_page_config(page_title="供应商数据下载", layout="wide")


# ========= 工具函数 =========
def safe_filename(name: str) -> str:
    name = str(name).strip() if name is not None else "未填写运输"
    if not name:
        name = "未填写运输"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name


def extract_date_from_filename(filename: str) -> str:
    """
    从文件名里提取日期：
    支持 20260407 / 2026-04-07 / 2026_04_07
    返回 YYYYMMDD
    """
    if not filename:
        return datetime.now().strftime("%Y%m%d")

    base = os.path.splitext(os.path.basename(filename))[0]

    m = re.search(r"(20\d{6})", base)
    if m:
        return m.group(1)

    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", base)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"

    return datetime.now().strftime("%Y%m%d")


def get_admin_password() -> str:
    try:
        return st.secrets["ADMIN_PASSWORD"]
    except Exception:
        return "admin123"


def load_passwords() -> dict:
    if os.path.exists(PASSWORD_FILE):
        with open(PASSWORD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_passwords(data: dict):
    with open(PASSWORD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_index() -> list:
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    return []


def save_index(data: list):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_date_display(yyyymmdd: str) -> str:
    if len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return yyyymmdd


def cleanup_old_files(retention_days: int = 30):
    """
    清理超出保留天数的历史文件。
    依据 source_date 判断是否过期。
    """
    records = load_index()
    today = datetime.now().date()
    kept = []

    for rec in records:
        source_date = rec.get("source_date", "")
        file_path = rec.get("file_path", "")

        keep_this = True
        try:
            file_date = datetime.strptime(source_date, "%Y%m%d").date()
            if (today - file_date).days > retention_days:
                keep_this = False
        except Exception:
            pass

        if keep_this and os.path.exists(file_path):
            kept.append(rec)
        else:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

    save_index(kept)


def save_uploaded_file(uploaded_file):
    """
    按文件名日期保存：
    例如 20260407_出库计划-20260407.xlsx
    同一天重复上传时，覆盖当天文件记录
    """
    cleanup_old_files(retention_days=30)

    source_name = uploaded_file.name
    source_date = extract_date_from_filename(source_name)
    saved_name = f"{source_date}_{safe_filename(source_name)}"
    file_path = os.path.join(ARCHIVE_DIR, saved_name)

    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    records = load_index()

    # 如果同一天已有记录，先删掉旧文件和旧记录
    new_records = []
    for rec in records:
        if rec.get("source_date") == source_date:
            old_path = rec.get("file_path", "")
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        else:
            if os.path.exists(rec.get("file_path", "")):
                new_records.append(rec)

    new_records.append({
        "source_name": source_name,
        "source_date": source_date,
        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "file_path": file_path
    })

    # 按日期倒序
    new_records.sort(key=lambda x: x.get("source_date", ""), reverse=True)
    save_index(new_records)


def get_archive_records() -> list:
    cleanup_old_files(retention_days=30)
    records = load_index()
    valid_records = [x for x in records if os.path.exists(x.get("file_path", ""))]
    valid_records.sort(key=lambda x: x.get("source_date", ""), reverse=True)
    return valid_records


def get_record_by_date(source_date: str):
    records = get_archive_records()
    for rec in records:
        if rec.get("source_date") == source_date:
            return rec
    return None


def find_transport_column(df: pd.DataFrame):
    """
    优先找表头“运输”
    找不到就退回 AN 列（第40列，索引39）
    """
    for col in df.columns:
        if str(col).strip() == "运输":
            return col

    if len(df.columns) >= 40:
        return df.columns[39]

    raise ValueError("找不到“运输”列，也没有 AN 列可用。")


def load_df_from_record(record):
    if not record:
        return None, None

    file_path = record.get("file_path", "")
    if not os.path.exists(file_path):
        return None, None

    df = pd.read_excel(file_path, dtype=str)
    df = df.fillna("")
    transport_col = find_transport_column(df)
    return df, transport_col


def get_supplier_list(df: pd.DataFrame, transport_col):
    values = df[transport_col].astype(str).str.strip()
    suppliers = [x for x in values.unique().tolist() if x]
    suppliers.sort()
    return suppliers


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="数据")
    output.seek(0)
    return output.getvalue()


# ========= 页面标题 =========
st.title("供应商数据下载网页")
st.caption("管理员上传总表后，系统按文件名日期归档；供应商可输入名称、密码，并按日期查看和下载自己的数据。")


# ========= 侧边栏 =========
with st.sidebar:
    st.header("使用说明")
    st.write("1. 管理员上传当天总表")
    st.write("2. 系统按文件名日期归档")
    st.write("3. 默认保留最近 30 天")
    st.write("4. 供应商输入自己的供应商名称和密码")
    st.write("5. 再按日期查看和下载自己的数据")
    st.info("如果你没配置 secrets.toml，管理员默认密码是：admin123")


# ========= 标签页 =========
tab_admin, tab_supplier = st.tabs(["管理员区", "供应商下载区"])


# ========= 管理员区 =========
with tab_admin:
    st.subheader("管理员登录")

    if "admin_ok" not in st.session_state:
        st.session_state.admin_ok = False

    admin_pwd_input = st.text_input("请输入管理员密码", type="password", key="admin_pwd_input")

    if st.button("进入管理员区"):
        if admin_pwd_input == get_admin_password():
            st.session_state.admin_ok = True
            st.success("管理员登录成功")
        else:
            st.session_state.admin_ok = False
            st.error("管理员密码错误")

    if st.session_state.admin_ok:
        st.markdown("---")
        st.subheader("1）上传当天总表")

        uploaded = st.file_uploader("请选择 Excel 文件", type=["xlsx", "xlsm"])

        if uploaded is not None:
            source_date = extract_date_from_filename(uploaded.name)
            st.write(f"已选择文件：{uploaded.name}")
            st.write(f"识别到日期：{normalize_date_display(source_date)}")
            st.write("说明：如果该日期已存在旧文件，上传后会覆盖该日期的旧版本。")

            if st.button("保存并归档"):
                save_uploaded_file(uploaded)
                st.success("文件已归档成功。")

        st.markdown("---")
        st.subheader("2）设置供应商密码")

        records = get_archive_records()
        latest_record = records[0] if records else None

        if latest_record:
            try:
                df, transport_col = load_df_from_record(latest_record)
                passwords = load_passwords()

                suppliers = get_supplier_list(df, transport_col)

                st.write(f"当前最新日期：{normalize_date_display(latest_record.get('source_date', ''))}")
                st.write(f"最新文件：{latest_record.get('source_name', '未知文件')}")
                st.write(f"识别到供应商数量：{len(suppliers)}")

                selected_for_pwd = st.selectbox("选择要设置密码的供应商", suppliers)
                new_password = st.text_input("输入该供应商的新密码", type="password", key="new_supplier_password")

                if st.button("保存这个供应商的密码"):
                    if not new_password.strip():
                        st.warning("密码不能为空")
                    else:
                        passwords[selected_for_pwd] = new_password.strip()
                        save_passwords(passwords)
                        st.success(f"已保存：{selected_for_pwd}")

                st.markdown("**已设置密码的供应商**")
                names = list(passwords.keys())
                if names:
                    st.write("、".join(names))
                else:
                    st.write("还没有设置任何供应商密码。")

            except Exception as e:
                st.error(f"读取最新归档文件失败：{e}")
        else:
            st.info("请先上传至少一份总表。")

        st.markdown("---")
        st.subheader("3）已归档日期")

        records = get_archive_records()
        if records:
            for rec in records:
                st.write(
                    f"日期：{normalize_date_display(rec.get('source_date', ''))} | "
                    f"文件：{rec.get('source_name', '')} | "
                    f"上传时间：{rec.get('upload_time', '')}"
                )
        else:
            st.write("当前没有归档文件。")


# ========= 供应商下载区 =========
with tab_supplier:
    st.subheader("供应商登录并下载")

    records = get_archive_records()

    if not records:
        st.warning("管理员还没有上传任何总表。")
    else:
        passwords = load_passwords()

        if "viewer_ok" not in st.session_state:
            st.session_state.viewer_ok = False
        if "viewer_supplier" not in st.session_state:
            st.session_state.viewer_supplier = ""

        input_supplier = st.text_input("请输入你的供应商名称").strip()
        supplier_pwd_input = st.text_input("请输入密码", type="password", key="supplier_pwd_input")

        if input_supplier != st.session_state.viewer_supplier:
            st.session_state.viewer_ok = False
            st.session_state.viewer_supplier = input_supplier

        if st.button("验证身份"):
            if not input_supplier:
                st.error("请输入供应商名称。")
                st.session_state.viewer_ok = False
            else:
                real_pwd = passwords.get(input_supplier)

                if real_pwd is None:
                    st.error("供应商名称不存在，或管理员还没有为该供应商设置密码。")
                    st.session_state.viewer_ok = False
                elif supplier_pwd_input != real_pwd:
                    st.error("密码错误。")
                    st.session_state.viewer_ok = False
                else:
                    st.session_state.viewer_ok = True
                    st.success("验证成功。")

        if st.session_state.viewer_ok and input_supplier:
            date_options = [rec["source_date"] for rec in records]
            date_labels = {d: normalize_date_display(d) for d in date_options}

            selected_date = st.selectbox(
                "请选择日期",
                options=date_options,
                format_func=lambda x: date_labels.get(x, x)
            )

            record = get_record_by_date(selected_date)
            if record:
                st.write(f"当前日期文件：{record.get('source_name', '未知文件')}")

                try:
                    df, transport_col = load_df_from_record(record)

                    if df is None:
                        st.error("该日期文件读取失败。")
                    else:
                        supplier_df = df[df[transport_col].astype(str).str.strip() == input_supplier].copy()

                        if supplier_df.empty:
                            st.warning("该日期下没有你的数据。")
                        else:
                            st.write(f"当前共有 {len(supplier_df)} 条数据")
                            st.dataframe(supplier_df, use_container_width=True, hide_index=True)

                            download_name = f"{selected_date}_{safe_filename(input_supplier)}.xlsx"
                            excel_bytes = dataframe_to_excel_bytes(supplier_df)

                            st.download_button(
                                label="下载我的 Excel",
                                data=excel_bytes,
                                file_name=download_name,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                except Exception as e:
                    st.error(f"读取数据失败：{e}")