"""Shared utilities for the Streamlit app."""
import streamlit as st
from supabase import create_client


def get_supabase_client():
    """Get authenticated Supabase client."""
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_SERVICE_ROLE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def fetch_courts(sb):
    """Fetch all courts from database."""
    res = sb.table("courts").select("id,name,city,district").order("name").execute()
    return res.data or []


def court_label(c: dict) -> str:
    """Generate a display label for a court."""
    city = c.get("city") or ""
    district = c.get("district") or ""
    suffix = " — ".join([x for x in [city, district] if x])
    return f"{c['name']}{(' — ' + suffix) if suffix else ''}"


def parse_float_or_none(s: str):
    """Parse a string to float or return None if empty."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    return float(s)


def upload_images_to_storage(sb, uploaded_files, court_id, bucket_name: str = "court-images"):
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

