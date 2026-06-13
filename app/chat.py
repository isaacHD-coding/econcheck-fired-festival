import streamlit as st


def main() -> None:
    st.set_page_config(page_title="EconCheck", layout="wide")
    st.title("EconCheck")
    st.status("Initialized", expanded=False)


if __name__ == "__main__":
    main()
