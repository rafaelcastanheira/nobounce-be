"""Shared utilities for the Streamlit app."""
import streamlit as st
import stripe
from supabase import create_client


def get_supabase_secrets():
    return  st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

def get_supabase_client():
    """Get authenticated Supabase client."""
    return create_client(*get_supabase_secrets())


def get_stripe():
    """Return the stripe module configured with the secret API key."""
    stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]
    return stripe


def sync_tournament_stripe(sb, tournament_id, name, price_eur, image_url=None):
    """Create/refresh the Stripe product, price and payment link for a tournament.

    Stripe prices are immutable, so when the amount changes we create a new
    price (and a new payment link) and archive the old ones. Returns the dict
    of fields written to the tournaments row, or None when nothing was done
    (e.g. free tournament). Raises on Stripe errors so the caller can surface them.
    """
    s = get_stripe()
    amount_cents = int(round(float(price_eur or 0) * 100))

    # Free tournament: archive any existing objects and clear the columns.
    if amount_cents <= 0:
        cur = (
            sb.table("tournaments")
            .select("stripe_product_id")
            .eq("id", tournament_id)
            .execute()
            .data
        )
        if cur and cur[0].get("stripe_product_id"):
            try:
                s.Product.modify(cur[0]["stripe_product_id"], active=False)
            except Exception:
                pass
        return {
            "stripe_product_id": None,
            "stripe_price_id": None,
            "stripe_payment_link": None,
        }

    cur = (
        sb.table("tournaments")
        .select("stripe_product_id,stripe_price_id,stripe_payment_link")
        .eq("id", tournament_id)
        .execute()
        .data
    )
    cur = cur[0] if cur else {}

    images = [image_url] if image_url else None

    # 1) Product — reuse if we already made one, else create.
    product_id = cur.get("stripe_product_id")
    if product_id:
        s.Product.modify(
            product_id, name=name, images=images, active=True,
            metadata={"tournament_id": tournament_id},
        )
    else:
        product = s.Product.create(
            name=name, images=images,
            metadata={"tournament_id": tournament_id},
        )
        product_id = product["id"]

    # 2) Price — reuse if the amount is unchanged, else create a new one
    #    and archive the previous price + payment link.
    price_id = cur.get("stripe_price_id")
    payment_link = cur.get("stripe_payment_link")
    existing_amount = None
    if price_id:
        try:
            existing_amount = s.Price.retrieve(price_id)["unit_amount"]
        except Exception:
            price_id = None

    if price_id is None or existing_amount != amount_cents:
        new_price = s.Price.create(
            product=product_id,
            unit_amount=amount_cents,
            currency="eur",
        )
        if price_id:
            try:
                s.Price.modify(price_id, active=False)
            except Exception:
                pass
        if payment_link:
            try:
                s.PaymentLink.modify(payment_link.split("/")[-1], active=False)
            except Exception:
                pass  # we store the URL; reconstructing the id is best-effort
        price_id = new_price["id"]
        payment_link = None

    # 3) Payment link — create one if we don't have a live one.
    if not payment_link:
        link = s.PaymentLink.create(
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={"tournament_id": tournament_id},
        )
        payment_link = link["url"]

    fields = {
        "stripe_product_id": product_id,
        "stripe_price_id": price_id,
        "stripe_payment_link": payment_link,
    }
    sb.table("tournaments").update(fields).eq("id", tournament_id).execute()
    return fields


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

