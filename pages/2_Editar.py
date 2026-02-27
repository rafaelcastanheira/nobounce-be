"""Page for updating existing courts and ratings."""
import streamlit as st
import sys
from pathlib import Path

# Add parent directory to path to import utils
sys.path.append(str(Path(__file__).parent.parent))
from utils import (
    get_supabase_client,
    fetch_courts,
    court_label,
    parse_float_or_none,
    upload_images_to_storage
)

st.set_page_config(page_title="Editar Campos & Ratings", layout="wide")

# Check authentication
if not st.session_state.get("authentication_status"):
    st.error("Fazer login primeiro.")
    st.stop()

st.title("✏️ Editar Campos & Ratings")
st.caption("Editar campos e ratings existentes")

# Get Supabase client
sb = get_supabase_client()

# -----------------------
# Tabs
# -----------------------
tab1, tab2, tab3 = st.tabs(["Editar Campo", "Editar Rating", "Editar Comentário"])

# =======================
# TAB 1: Update Court
# =======================
with tab1:
    st.subheader("Editar Campo")

    courts = fetch_courts(sb)
    if not courts:
        st.warning("Não foram encontrados campos.")
        st.stop()

    # Court selection
    labels = [court_label(c) for c in courts]
    label_to_id = {court_label(c): c["id"] for c in courts}

    selected_label = st.selectbox("Selecionar um Campo para editar", labels, key="update_court_select")
    selected_court_id = label_to_id[selected_label]

    # Fetch full court details
    court_result = sb.table("courts").select("*").eq("id", selected_court_id).execute()

    if not court_result.data:
        st.error("Erro ao carregar dados do campo.")
        st.stop()

    court_data = court_result.data[0]

    st.info(f"A editar: **{court_data['name']}** (ID: {court_data['id']})")

    with st.form("update_court_form"):
        col1, col2 = st.columns(2)

        with col1:
            name_in = st.text_input("Nome *", value=court_data.get('name', ''))
            address_in = st.text_input("Morada", value=court_data.get('address', '') or '')
            city_in = st.text_input("Concelho", value=court_data.get('city', '') or '')
            district_in = st.text_input("Distrito", value=court_data.get('district', '') or '')

        with col2:
            lat_val = court_data.get('latitude')
            lon_val = court_data.get('longitude')
            lat_in = st.text_input("Latitude (opcional)", value=str(lat_val) if lat_val is not None else '')
            lon_in = st.text_input("Longitude (opcional)", value=str(lon_val) if lon_val is not None else '')
            insta_in = st.text_input("Instagram URL (opcional)", value=court_data.get('instagram_url', '') or '')
            tiktok_in = st.text_input("TikTok URL (opcional)", value=court_data.get('tiktok_url', '') or '')

        user_created_by_in = st.text_input("Utilizador Criado Por (UUID, opcional)",
                                           value=court_data.get('user_created_by', '') or '',
                                           key="court_user_created_by")

        # Show existing images
        existing_images = court_data.get('image_urls', [])
        if existing_images:
            st.write(f"Imagens atuais: {len(existing_images)}")
            cols = st.columns(min(len(existing_images), 4))
            for idx, img_url in enumerate(existing_images[:4]):
                with cols[idx]:
                    st.image(img_url, width=150)

        # New file uploader for additional/replacement images
        uploaded_files = st.file_uploader("Upload de Novas Imagens (irá substituir as existentes)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

        submitted = st.form_submit_button("Atualizar Campo")

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
                "admin_created_by": admin_email,  # Track who last updated
                "user_created_by": user_created_by_in.strip() if user_created_by_in.strip() else None,
            }
        except ValueError as e:
            st.error(f"Latitude/Longitude tem que ser números válidos: {e}")
            st.stop()

        try:
            # Upload new images if provided
            if uploaded_files:
                with st.spinner(f"A fazer upload de {len(uploaded_files)} imagem(nes)..."):
                    image_urls = upload_images_to_storage(sb, uploaded_files, selected_court_id)
                    if image_urls:
                        payload["image_urls"] = image_urls

            # Update the court
            sb.table("courts").update(payload).eq("id", selected_court_id).execute()
            st.success(f"Campo atualizado ✅ (ID: {selected_court_id})")

        except Exception as e:
            st.error(f"Erro ao atualizar o campo: {e}")

# =======================
# TAB 2: Update Court Rating
# =======================
with tab2:
    st.subheader("Editar Rating")

    courts = fetch_courts(sb)
    if not courts:
        st.warning("Não foram encontrados campos.")
        st.stop()

    labels = [court_label(c) for c in courts]
    label_to_id = {court_label(c): c["id"] for c in courts}

    selected_label = st.selectbox("Selecionar Campo", labels, key="update_rating_select")
    selected_court_id = label_to_id[selected_label]

    # Fetch all ratings for the selected court
    rating_result = sb.table("court_ratings").select("*").eq("court_id", selected_court_id).execute()

    if not rating_result.data:
        st.warning("Não existem ratings para este campo.")
        existing_rating = None
    else:
        # Build labels for each rating so the user can pick one
        def rating_label(r):
            src = r.get("source", "?")
            overall = r.get("overall", "?")
            user = r.get("user_id") or "—"
            return f"{src} | Overall: {overall} | User: {user}"

        rating_labels = [rating_label(r) for r in rating_result.data]
        selected_rating_label = st.selectbox(
            "Selecionar Rating para editar",
            rating_labels,
            key="update_rating_pick",
        )
        selected_rating_idx = rating_labels.index(selected_rating_label)
        existing_rating = rating_result.data[selected_rating_idx]
        st.info(f"A editar rating **{existing_rating.get('source')}** para: **{selected_label}**")

    with st.form("update_rating_form"):
        colA, colB, colC = st.columns(3)

        with colA:
            overall = st.number_input("Overall (0-10) *", 0.0, 10.0,
                                     value=float(existing_rating.get('overall', 0.0)) if existing_rating else 0.0,
                                     step=0.25, format="%.2f")
            rim = st.number_input("Aro (0-10, opcional)", 0.0, 10.0,
                                 value=float(existing_rating['rim']) if existing_rating and existing_rating.get('rim') is not None else None,
                                 step=0.25, format="%.2f")
            floor = st.number_input("Chão (0-10, opcional)", 0.0, 10.0,
                                   value=float(existing_rating['floor']) if existing_rating and existing_rating.get('floor') is not None else None,
                                   step=0.25, format="%.2f")

        with colB:
            court_spacing = st.number_input("Espaço (0-10, opcional)", 0.0, 10.0,
                                           value=float(existing_rating['court_spacing']) if existing_rating and existing_rating.get('court_spacing') is not None else None,
                                           step=0.25, format="%.2f")
            bench = st.number_input("Banco (0-10, opcional)", 0.0, 10.0,
                                   value=float(existing_rating['bench']) if existing_rating and existing_rating.get('bench') is not None else None,
                                   step=0.25, format="%.2f")
            water = st.number_input("Água (0-10, opcional)", 0.0, 10.0,
                                   value=float(existing_rating['water']) if existing_rating and existing_rating.get('water') is not None else None,
                                   step=0.25, format="%.2f")

        with colC:
            backboard = st.number_input("Tabela (0-10, opcional)", 0.0, 10.0,
                                       value=float(existing_rating['backboard']) if existing_rating and existing_rating.get('backboard') is not None else None,
                                       step=0.25, format="%.2f")
            source_options = ["NO_BOUNCE", "COMMUNITY"]
            source_index = source_options.index(existing_rating.get('source', 'NO_BOUNCE')) if existing_rating and existing_rating.get('source') in source_options else 0
            source = st.selectbox("Fonte", source_options, index=source_index)

        user_id_in = st.text_input("ID do Utilizador (UUID, opcional)",
                                   value=existing_rating.get('user_id', '') or '' if existing_rating else '',
                                   key="rating_user_id")

        submitted = st.form_submit_button("Atualizar Rating")

    if submitted:
        if not existing_rating:
            st.error("Não existe rating selecionado para atualizar.")
            st.stop()

        admin_email = st.session_state.get('username')
        rating_id = existing_rating["id"]

        payload = {
            "court_id": selected_court_id,
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
            sb.table("court_ratings").update(payload).eq("id", rating_id).execute()
            st.success("Rating atualizado ✅")
        except Exception as e:
            st.error(f"Erro ao atualizar rating: {e}")

# =======================
# TAB 3: Update Comment
# =======================
with tab3:
    st.subheader("Editar Comentário")

    courts_comments = fetch_courts(sb)
    if not courts_comments:
        st.warning("Não foram encontrados campos.")
        st.stop()

    comment_labels = [court_label(c) for c in courts_comments]
    comment_label_to_id = {court_label(c): c["id"] for c in courts_comments}

    selected_comment_label = st.selectbox("Selecionar Campo", comment_labels, key="update_comment_court")
    selected_comment_court_id = comment_label_to_id[selected_comment_label]

    # Fetch all comments for the selected court
    comments_result = sb.table("court_comments").select("*").eq("court_id", selected_comment_court_id).execute()

    if not comments_result.data:
        st.warning("Não existem comentários para este campo.")
        existing_comment = None
    else:
        # Build labels for each comment so the user can pick one
        def comment_label_fn(c):
            user = c.get("user_id") or "—"
            text = (c.get("comment") or "")[:50]
            return f"User: {user} | {text}..."

        comment_pick_labels = [comment_label_fn(c) for c in comments_result.data]
        selected_comment_pick = st.selectbox(
            "Selecionar Comentário para editar",
            comment_pick_labels,
            key="update_comment_pick",
        )
        selected_comment_idx = comment_pick_labels.index(selected_comment_pick)
        existing_comment = comments_result.data[selected_comment_idx]
        st.info(f"A editar comentário de **{existing_comment.get('user_id', '—')}**")

    with st.form("update_comment_form"):
        edit_user_id = st.text_input(
            "ID do Utilizador (UUID) *",
            value=existing_comment.get('user_id', '') or '' if existing_comment else '',
            key="edit_comment_user_id",
        )
        edit_comment_text = st.text_area(
            "Comentário *",
            value=existing_comment.get('comment', '') or '' if existing_comment else '',
            key="edit_comment_text",
        )

        submitted_comment = st.form_submit_button("Atualizar Comentário")

    if submitted_comment:
        if not existing_comment:
            st.error("Não existe comentário selecionado para atualizar.")
            st.stop()
        if not edit_user_id.strip():
            st.error("ID do Utilizador é obrigatório.")
            st.stop()
        if not edit_comment_text.strip():
            st.error("Comentário é obrigatório.")
            st.stop()

        comment_id = existing_comment["id"]

        payload = {
            "user_id": edit_user_id.strip(),
            "comment": edit_comment_text.strip(),
        }

        try:
            sb.table("court_comments").update(payload).eq("id", comment_id).execute()
            st.success("Comentário atualizado ✅")
        except Exception as e:
            st.error(f"Erro ao atualizar comentário: {e}")

