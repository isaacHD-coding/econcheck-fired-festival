import streamlit as st


def main() -> None:
    st.set_page_config(page_title="EconCheck Observability", layout="wide")
    st.title("Observability")
    st.status("Initialized", expanded=False)


if __name__ == "__main__":
    main()
