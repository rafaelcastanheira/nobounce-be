import streamlit as st
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))
from utils import (
    get_supabase_client,
    fetch_courts,
    court_label,
    parse_float_or_none,
    upload_images_to_storage
)

st.set_page_config(page_title="Adicionar Campos & Ratings", layout="wide", page_icon="🏀")

# Check authentication
if not st.session_state.get("authentication_status"):
    st.error("Fazer login primeiro.")
    st.stop()

st.title("➕ Adicionar Campos & Ratings")
st.caption("ATENÇÃO: qualquer adição feita aqui é visível na aplicação.")

# Get Supabase client
sb = get_supabase_client()

# -----------------------
# Tabs
# -----------------------
tab1, tab2 = st.tabs(["Adicionar Campo", "Adicionar Rating"])

# =======================
# TAB 1: Add Court
# =======================
with tab1:
    st.subheader("Adicionar Campo")

    with st.form("add_court_form"):
        col1, col2 = st.columns(2)

        with col1:
            name_in = st.text_input("Nome *")
            address_in = st.text_input("Morada")
            city_in = st.text_input("Concelho")
            district_in = st.text_input("Distrito")

        with col2:
            lat_in = st.text_input("Latitude (optional)")
            lon_in = st.text_input("Longitude (optional)")
            insta_in = st.text_input("Instagram URL (optional)")
            tiktok_in = st.text_input("TikTok URL (optional)")

        uploaded_files = st.file_uploader("Upload de Imagens do Campo", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

        submitted = st.form_submit_button("Criar Campo")

    if submitted:
        if not name_in.strip():
            st.error("Nome é obrigatório.")
            st.stop()

        admin_email = st.session_state.get('username')

        try:
            payload = {
                "name": name_in.strip(),
                "address": address_in.strip() if address_in.strip() else None,
                "city": city_in.strip() if city_in.strip() else None,
                "district": district_in.strip() if district_in.strip() else None,
                "latitude": parse_float_or_none(lat_in),
                "longitude": parse_float_or_none(lon_in),
                "instagram_url": insta_in.strip() if insta_in.strip() else None,
                "tiktok_url": tiktok_in.strip() if tiktok_in.strip() else None,
                "image_urls": [],
                "admin_created_by": admin_email,
            }
        except ValueError as e:
            st.error(f"Latitude/Longitude tem que ser numéros válidos: {e}")
            st.stop()

        try:
            result = sb.table("courts").insert(payload).execute()
            court_data = result.data[0] if result.data else None

            if not court_data:
                st.error("Erro na criação do campo")
                st.stop()

            court_id = court_data['id']

            if uploaded_files:
                with st.spinner(f"Uploading {len(uploaded_files)} image(s)..."):
                    image_urls = upload_images_to_storage(sb, uploaded_files, court_id)

                    if image_urls:
                        sb.table("courts").update({"image_urls": image_urls}).eq("id", court_id).execute()
                        st.success(f"Campo criado ✅ (ID: {court_id}) com {len(image_urls)} imagem(nes)")
                    else:
                        st.success(f"Campo criado ✅ (ID: {court_id}) sem images")
            else:
                st.success(f"Campo criado ✅ (ID: {court_id})")
        except Exception as e:
            st.error(f"Erro em criar o Campo: {e}")

# =======================
# TAB 2: Add Court Rating
# =======================
with tab2:
    st.subheader("Adicionar Rating (No Bounce)")

    courts = fetch_courts(sb)
    if not courts:
        st.warning("Não foram encontrados campos")
        st.stop()

    labels = [court_label(c) for c in courts]
    label_to_id = {court_label(c): c["id"] for c in courts}

    with st.form("add_rating_form"):
        selected = st.selectbox("Campo *", labels)
        court_id = label_to_id[selected]

        colA, colB, colC = st.columns(3)

        with colA:
            overall = st.number_input("Overall (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            rim = st.number_input("Aro (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            floor = st.number_input("Chão (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")

        with colB:
            court_spacing = st.number_input("Espaço (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            bench = st.number_input("Banco (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            water = st.number_input("Água (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")

        with colC:
            backboard = st.number_input("Tabela (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            source = st.selectbox("Fonte", ["NO_BOUNCE"], index=0)

        submitted = st.form_submit_button("Criar Rating")

    if submitted:
        admin_email = st.session_state.get('username')

        payload = {
            "court_id": court_id,
            "source": source,
            "overall": round(float(overall), 2),
            "rim": round(float(rim), 2),
            "floor": round(float(floor), 2),
            "court_spacing": round(float(court_spacing), 2),
            "bench": round(float(bench), 2),
            "water": round(float(water), 2),
            "backboard": round(float(backboard), 2),
            "admin_created_by": admin_email,
        }

        try:
            sb.table("court_ratings").upsert(payload, on_conflict="court_id,source").execute()
            st.success("Rating criado ✅")
        except Exception as e:
            st.error(f"Erro ao criar rating: {e}")
