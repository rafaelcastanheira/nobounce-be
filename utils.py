"""Shared utilities for the Streamlit app."""
import streamlit as st
from supabase import create_client


def get_supabase_secrets():
    return  st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

def get_supabase_client():
    """Get authenticated Supabase client."""
    return create_client(*get_supabase_secrets())


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


def fetch_tournaments(sb):
    """Fetch all tournaments, newest first."""
    res = (
        sb.table("tournaments")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=300, show_spinner="A carregar jogadores...")
def fetch_profiles(_sb, page_size: int = 1000):
    """Fetch all profiles (app users) for roster selection.

    Supabase/PostgREST caps a single response at 1000 rows, so we page
    through with .range() until we've pulled everything.

    Cached for 5 minutes. The `_sb` arg is underscore-prefixed so Streamlit
    skips hashing the (unhashable) Supabase client. Call
    `fetch_profiles.clear()` to force a refresh.
    """
    rows = []
    start = 0
    while True:
        res = (
            _sb.table("profiles")
            .select("id,display_name,city")
            .order("display_name")
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def tournament_label(t: dict) -> str:
    """Display label for a tournament."""
    size = t.get("team_size")
    size_txt = f"{size}x{size}" if size else "?"
    return f"{t.get('name', '—')} ({size_txt}) · {t.get('status', '?')}"


def team_label(t: dict) -> str:
    """Display label for a team."""
    seed = t.get("seed")
    return f"{t.get('name', '—')}" + (f" (seed {seed})" if seed is not None else "")


def profile_label(p: dict) -> str:
    """Display label for a profile."""
    name = p.get("display_name") or "—"
    city = p.get("city")
    return f"{name}{(' · ' + city) if city else ''} · {str(p['id'])[:8]}"


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

