import streamlit as st
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from supabase import create_client


st.set_page_config(page_title="Sheeper Admin", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

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

st.title("No Bounce Internal Admin")
st.caption("Adicionar campos e ratings (No Bounce)")

# -----------------------
# Helpers
# -----------------------
def fetch_courts():
    res = sb.table("courts").select("id,name,city,district").order("name").execute()
    return res.data or []

def court_label(c: dict) -> str:
    city = c.get("city") or ""
    district = c.get("district") or ""
    suffix = " — ".join([x for x in [city, district] if x])
    return f"{c['name']}{(' — ' + suffix) if suffix else ''}"

def parse_float_or_none(s: str):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    return float(s)

def upload_images_to_storage(uploaded_files, court_id, bucket_name: str = "court-images"):
    """Upload multiple images to Supabase Storage and return their public URLs."""
    image_urls = []

    for idx, uploaded_file in enumerate(uploaded_files):
        try:
            # Generate filename using court_id as folder
            file_ext = uploaded_file.name.split('.')[-1]
            unique_filename = f"{court_id}/{idx + 1}.{file_ext}"

            # Read file bytes
            file_bytes = uploaded_file.read()

            # Upload to Supabase Storage with upsert option
            # Using service role should bypass RLS, but we add upsert just in case
            result = sb.storage.from_(bucket_name).upload(
                unique_filename,
                file_bytes,
                file_options={
                    "content-type": uploaded_file.type,
                    "upsert": "true"
                }
            )

            # Get public URL
            public_url = sb.storage.from_(bucket_name).get_public_url(unique_filename)
            image_urls.append(public_url)

        except Exception as e:
            st.warning(f"Failed to upload {uploaded_file.name}: {e}")
            continue

    return image_urls

# -----------------------
# Tabs
# -----------------------
tab1, tab2 = st.tabs(["Add Court", "Add Court Rating"])

# =======================
# TAB 1: Add Court
# =======================
with tab1:
    st.subheader("Add Court")

    with st.form("add_court_form"):
        col1, col2 = st.columns(2)

        with col1:
            name_in = st.text_input("Name *")
            address_in = st.text_input("Address")
            city_in = st.text_input("City (Concelho)")
            district_in = st.text_input("District (Distrito)")

        with col2:
            lat_in = st.text_input("Latitude (optional)")
            lon_in = st.text_input("Longitude (optional)")
            insta_in = st.text_input("Instagram URL (optional)")
            tiktok_in = st.text_input("TikTok URL (optional)")

        # New file uploader for images
        uploaded_files = st.file_uploader("Upload Court Images", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

        submitted = st.form_submit_button("Create Court")

    if submitted:
        if not name_in.strip():
            st.error("Name is required.")
            st.stop()

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
                "image_urls": [],  # start empty
            }
        except ValueError as e:
            st.error(f"Latitude/Longitude must be valid numbers (or empty): {e}")
            st.stop()

        try:
            # First, create the court to get the ID
            result = sb.table("courts").insert(payload).execute()
            court_data = result.data[0] if result.data else None

            if not court_data:
                st.error("Failed to create court: No data returned")
                st.stop()

            court_id = court_data['id']

            # Upload images if provided
            if uploaded_files:
                with st.spinner(f"Uploading {len(uploaded_files)} image(s)..."):
                    image_urls = upload_images_to_storage(uploaded_files, court_id)

                    # Update the court with image URLs
                    if image_urls:
                        sb.table("courts").update({"image_urls": image_urls}).eq("id", court_id).execute()
                        st.success(f"Court created ✅ (ID: {court_id}) with {len(image_urls)} image(s)")
                    else:
                        st.success(f"Court created ✅ (ID: {court_id}) but no images were uploaded")
            else:
                st.success(f"Court created ✅ (ID: {court_id})")

            st.info("Refresh the page or switch tabs to see the updated court list.")
        except Exception as e:
            st.error(f"Failed to create court: {e}")

# =======================
# TAB 2: Add Court Rating
# =======================
with tab2:
    st.subheader("Add Court Rating (No Bounce)")

    courts = fetch_courts()
    if not courts:
        st.warning("No courts found. Add a court first.")
        st.stop()

    labels = [court_label(c) for c in courts]
    label_to_id = {court_label(c): c["id"] for c in courts}

    with st.form("add_rating_form"):
        selected = st.selectbox("Court *", labels)
        court_id = label_to_id[selected]

        colA, colB, colC = st.columns(3)

        # step=0.25 gives you 0.00/0.25/0.50 etc. Adjust if you want 0.05.
        with colA:
            overall = st.number_input("overall (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            rim = st.number_input("rim (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            floor = st.number_input("floor (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")

        with colB:
            court_spacing = st.number_input("court_spacing (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            bench = st.number_input("bench (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            water = st.number_input("water (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")

        with colC:
            backboard = st.number_input("backboard (0-10)", 0.0, 10.0, 0.0, step=0.25, format="%.2f")
            source = st.selectbox("source", ["NO_BOUNCE"], index=0)

        submitted = st.form_submit_button("Save Rating")

    if submitted:
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
        }

        try:
            # Requires unique(court_id, source) in DB
            sb.table("court_ratings").upsert(payload, on_conflict="court_id,source").execute()
            st.success("Rating saved ✅")
        except Exception as e:
            st.error(f"Failed to save rating: {e}")
