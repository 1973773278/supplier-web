import os
import io
import json
import re
from datetime import datetime

import pandas as pd
import streamlit as st

# ========= 基础路径 =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_FILE = os.path.join(DATA_DIR, "current.xlsx")
META_FILE = os.path.join(DATA_DIR, "meta.json")
PASSWORD_FILE = os.path.join(DATA_DIR, "passwords.json")

os.makedirs(DATA_DIR, exist_ok=True)

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
    """
    优先从 st.secrets 读管理员密码。
    如果你没配 secrets.toml，就先用默认密码 admin123。
    """
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


def save_uploaded_file(uploaded_file):
    with open(UPLOAD_FILE, "wb") as f:
        f.write(uploaded_file.getbuffer())

    meta = {
        "source_name": uploaded_file.name,
        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_meta() -> dict:
    if os.path.exists(META_FILE):
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


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


def load_current_df():
    if not os.path.exists(UPLOAD_FILE):
        return None, None, None

    df = pd.read_excel(UPLOAD_FILE, dtype=str)
    df = df.fillna("")

    transport_col = find_transport_column(df)
    meta = load_meta()
    return df, transport_col, meta


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
st.caption("管理员上传总表后，供应商可按姓名 + 密码查看并下载自己的数据。")


# ========= 侧边栏：说明 =========
with st.sidebar:
    st.header("使用说明")
    st.write("1. 管理员先上传当天总表")
    st.write("2. 给供应商设置密码")
    st.write("3. 供应商选择自己的名字并输入密码")
    st.write("4. 查看并下载自己的 Excel")
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
            st.write(f"已选择文件：{uploaded.name}")
            if st.button("保存为当前总表"):
                save_uploaded_file(uploaded)
                st.success("总表已保存，供应商现在可以查看最新数据了。")

        st.markdown("---")
        st.subheader("2）设置供应商密码")

        try:
            df, transport_col, meta = load_current_df()
        except Exception as e:
            df, transport_col, meta = None, None, None
            st.error(f"读取当前总表失败：{e}")

        if df is not None:
            suppliers = get_supplier_list(df, transport_col)
            passwords = load_passwords()

            st.write(f"当前总表来源：{meta.get('source_name', '未知文件')}")
            st.write(f"上传时间：{meta.get('upload_time', '未知时间')}")
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
        else:
            st.info("请先上传总表，再设置供应商密码。")


# ========= 供应商下载区 =========
with tab_supplier:
    st.subheader("供应商登录并下载")

    try:
        df, transport_col, meta = load_current_df()
    except Exception as e:
        df, transport_col, meta = None, None, None
        st.error(f"读取当前总表失败：{e}")

    if df is None:
        st.warning("管理员还没有上传总表。")
    else:
        st.write(f"当前总表：{meta.get('source_name', '未知文件')}")
        st.write(f"更新时间：{meta.get('upload_time', '未知时间')}")

        suppliers = get_supplier_list(df, transport_col)
        passwords = load_passwords()

        if "viewer_ok" not in st.session_state:
            st.session_state.viewer_ok = False
        if "viewer_supplier" not in st.session_state:
            st.session_state.viewer_supplier = ""

        selected_supplier = st.selectbox("请选择你的供应商名称", suppliers)

        # 如果切换了供应商，重置登录状态
        if selected_supplier != st.session_state.viewer_supplier:
            st.session_state.viewer_ok = False
            st.session_state.viewer_supplier = selected_supplier

        supplier_pwd_input = st.text_input("请输入密码", type="password", key="supplier_pwd_input")

        if st.button("查看我的数据"):
            real_pwd = passwords.get(selected_supplier, None)

            if real_pwd is None:
                st.error("管理员还没有给这个供应商设置密码。")
                st.session_state.viewer_ok = False
            elif supplier_pwd_input != real_pwd:
                st.error("密码错误。")
                st.session_state.viewer_ok = False
            else:
                st.session_state.viewer_ok = True
                st.success("验证成功。")

        if st.session_state.viewer_ok:
            supplier_df = df[df[transport_col].astype(str).str.strip() == selected_supplier].copy()
            st.write(f"当前共有 {len(supplier_df)} 条数据")
            st.dataframe(supplier_df, use_container_width=True, hide_index=True)

            date_prefix = extract_date_from_filename(meta.get("source_name", ""))
            download_name = f"{date_prefix}_{safe_filename(selected_supplier)}.xlsx"
            excel_bytes = dataframe_to_excel_bytes(supplier_df)

            st.download_button(
                label="下载我的 Excel",
                data=excel_bytes,
                file_name=download_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )