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
tab1, tab2, tab3 = st.tabs(["Adicionar Campo", "Adicionar Rating", "Adicionar Comentário"])

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
            lat_in = st.text_input("Latitude (opcional)")
            lon_in = st.text_input("Longitude (opcional)")
            insta_in = st.text_input("Instagram URL (opcional)")
            tiktok_in = st.text_input("TikTok URL (opcional)")

        user_created_by_in = st.text_input("Utilizador Criado Por (UUID, opcional)", key="court_user_created_by")

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
                "user_created_by": user_created_by_in.strip() if user_created_by_in.strip() else None,
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
                with st.spinner(f"A carregar {len(uploaded_files)} imagem(nes)..."):
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
            overall = st.number_input("Overall (0-10) *", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            rim = st.number_input("Aro (0-10, opcional)", 0.0, 10.0, value=None, step=0.25, format="%.2f")
            floor = st.number_input("Chão (0-10, opcional)", 0.0, 10.0, value=None, step=0.25, format="%.2f")

        with colB:
            court_spacing = st.number_input("Espaço (0-10, opcional)", 0.0, 10.0, value=None, step=0.25, format="%.2f")
            bench = st.number_input("Banco (0-10, opcional)", 0.0, 10.0, value=None, step=0.25, format="%.2f")
            water = st.number_input("Água (0-10, opcional)", 0.0, 10.0, value=None, step=0.25, format="%.2f")

        with colC:
            backboard = st.number_input("Tabela (0-10, opcional)", 0.0, 10.0, value=None, step=0.25, format="%.2f")
            source = st.selectbox("Fonte", ["NO_BOUNCE", "COMMUNITY"], index=0)

        user_id_in = st.text_input("ID do Utilizador (UUID, opcional)", key="rating_user_id")

        submitted = st.form_submit_button("Criar Rating")

    if submitted:
        admin_email = st.session_state.get('username')

        payload = {
            "court_id": court_id,
            "source": source,
            "overall": round(float(overall), 2),
            "rim": round(float(rim), 2) if rim is not None else None,
            "floor": round(float(floor), 2) if floor is not None else None,
            "court_spacing": round(float(court_spacing), 2) if court_spacing is not None else None,
            "bench": round(float(bench), 2) if bench is not None else None,
            "water": round(float(water), 2) if water is not None else None,
            "backboard": round(float(backboard), 2) if backboard is not None else None,
            "admin_created_by": admin_email,
            "user_id": user_id_in.strip() if user_id_in.strip() else None,
        }

        try:
            sb.table("court_ratings").upsert(payload, on_conflict="court_id,source").execute()
            st.success("Rating criado ✅")
        except Exception as e:
            st.error(f"Erro ao criar rating: {e}")

# =======================
# TAB 3: Add Comment
# =======================
with tab3:
    st.subheader("Adicionar Comentário")

    courts_comments = fetch_courts(sb)
    if not courts_comments:
        st.warning("Não foram encontrados campos.")
        st.stop()

    comment_labels = [court_label(c) for c in courts_comments]
    comment_label_to_id = {court_label(c): c["id"] for c in courts_comments}

    with st.form("add_comment_form"):
        selected_comment_court = st.selectbox("Campo *", comment_labels, key="add_comment_court")
        comment_court_id = comment_label_to_id[selected_comment_court]

        comment_user_id = st.text_input("ID do Utilizador (UUID) *", key="add_comment_user_id")
        comment_text = st.text_area("Comentário *", key="add_comment_text")

        submitted_comment = st.form_submit_button("Criar Comentário")

    if submitted_comment:
        if not comment_user_id.strip():
            st.error("ID do Utilizador é obrigatório.")
            st.stop()
        if not comment_text.strip():
            st.error("Comentário é obrigatório.")
            st.stop()

        payload = {
            "court_id": comment_court_id,
            "user_id": comment_user_id.strip(),
            "comment": comment_text.strip(),
        }

        try:
            sb.table("court_comments").insert(payload).execute()
            st.success("Comentário criado ✅")
        except Exception as e:
            st.error(f"Erro ao criar comentário: {e}")

