import streamlit as st
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth


st.set_page_config(
    page_title="No Bounce Admin",
    layout="wide",
    page_icon="🏀"
)

# Authentication
with open("auth.yaml", "r", encoding="utf-8") as f:
    config = yaml.load(f, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)

authenticator.login()

if st.session_state.get("authentication_status") is False:
    st.error("Email/password inválidos.")
    st.stop()
if st.session_state.get("authentication_status") is None:
    st.info("Faz login para continuares.")
    st.stop()

authenticator.logout("Logout", "sidebar")
st.sidebar.success(f"Logado como: {st.session_state.get('name')}")

st.title("No Bounce 🏀 Admin")
st.caption("Gestão de campos e ratings")


st.markdown("""
### Bem-vindo ao Painel Admin No Bounce

Usa a barra lateral para navegar entre as páginas:

- **Adicionar**: Adicionar novos campos e ratings
- **Editar**: Editar campos e ratings existentes

Seleciona uma página na barra lateral para começar.
""")

st.info("👈 Seleciona uma página na barra lateral para continuar")

# Links úteis
st.markdown("---")
st.subheader("🔗 Links Úteis")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**🌐 Website**")
    st.link_button("No Bounce Website", "https://www.nobounce.pt/", use_container_width=True)

with col2:
    st.markdown("**📱 App Store**")
    st.button("App Store (Em breve)", disabled=True, use_container_width=True)

with col3:
    st.markdown("**🤖 Play Store**")
    st.button("Play Store (Em breve)", disabled=True, use_container_width=True)
