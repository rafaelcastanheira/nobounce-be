import streamlit as st

from utils import require_login


st.set_page_config(
    page_title="No Bounce Admin",
    layout="wide",
    page_icon="🏀"
)

# Authentication: Google login via st.login, restricted to allowed emails
require_login()

st.title("No Bounce 🏀 Admin")
st.caption("Gestão de campos e ratings")


st.markdown("""
### Bem-vindo ao Painel Admin No Bounce

Usa a barra lateral para navegar entre as páginas:

- **Adicionar**: Adicionar novos campos e ratings
- **Editar**: Editar campos e ratings existentes
- **Torneios**: Gerir torneios, equipas, grupos e jogos

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
    st.link_button("App Store", "https://apps.apple.com/us/app/no-bounce/id6757975858", use_container_width=True)

with col3:
    st.markdown("**🤖 Play Store**")
    st.link_button("Play Store", "https://play.google.com/store/apps/details?id=com.nobounceapp", use_container_width=True)
