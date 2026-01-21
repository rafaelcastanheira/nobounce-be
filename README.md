# nobounce-be
No Bounce BE

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure secrets

**For local development (Recommended):**

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Then edit `.env` and add your credentials:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
```

**For Streamlit Cloud deployment:**

Create `.streamlit/secrets.toml` (for cloud deployment only):

```bash
cp .streamlit/secrets.toml .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml` with your credentials.

### 3. Run the app

```bash
uv run streamlit run home.py
```

## Security Notes

- ⚠️ **Never commit `.env` or `.streamlit/secrets.toml` to version control**
- The app will automatically load credentials from `.env` file first
- If `.env` is not found, it will fall back to `.streamlit/secrets.toml`
- For production deployments, use environment variables or Streamlit Cloud secrets
