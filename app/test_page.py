"""极简测试：验证 Streamlit 页面渲染"""
import streamlit as st

st.title("Test - Page Rendering Works")
st.write("If you can see this, Streamlit is rendering correctly.")

with st.sidebar:
    st.write("Sidebar works")
    page = st.radio("Pick", ["A", "B", "C"])

st.write(f"You selected: {page}")

if page == "A":
    st.success("Page A content here")
    st.info("This is page A")
elif page == "B":
    st.warning("Page B content here")
    st.info("This is page B")
else:
    st.error("Page C content here")
    st.info("This is page C")
