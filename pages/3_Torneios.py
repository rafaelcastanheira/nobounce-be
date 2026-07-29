"""Page for managing tournaments: tournaments, teams, groups and matches."""
import math
import random
from datetime import date, datetime, timezone
import sys
from pathlib import Path

import streamlit as st

# Add parent directory to path to import utils
sys.path.append(str(Path(__file__).parent.parent))
from utils import (
    get_supabase_client,
    fetch_courts,
    court_label,
    fetch_tournaments,
    fetch_profiles,
    tournament_label,
    team_label,
    profile_label,
    upload_images_to_storage,
    sync_tournament_stripe,
)

TOURNAMENT_IMAGES_BUCKET = "tournament-images"

st.set_page_config(page_title="Torneios", layout="wide", page_icon="🏆")

# Check authentication
if not st.session_state.get("authentication_status"):
    st.error("Fazer login primeiro.")
    st.stop()

st.title("🏆 Torneios")
st.caption("ATENÇÃO: qualquer alteração feita aqui é visível na aplicação.")

sb = get_supabase_client()

FORMATS = {
    "knockout": "Eliminatória direta",
    "group_then_knockout": "Fase de grupos + Eliminatória",
    "streetball": "Roda Bota Fora",
}
STATUSES = ["draft", "registration", "group_stage", "knockout", "completed", "cancelled"]
MATCH_STATUSES = ["scheduled", "in_progress", "completed", "cancelled"]


# -----------------------
# Helpers (local)
# -----------------------
def fetch_teams(tournament_id):
    res = (
        sb.table("tournament_teams")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("name")
        .execute()
    )
    return res.data or []


def fetch_groups(tournament_id):
    res = (
        sb.table("tournament_groups")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("name")
        .execute()
    )
    return res.data or []


def fetch_matches(tournament_id):
    res = (
        sb.table("tournament_matches")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("stage")
        .order("round")
        .order("bracket_position")
        .execute()
    )
    return res.data or []


def tournament_selectbox(key, label="Torneio *", format_filter=None):
    """Render a tournament selectbox and return the selected tournament dict (or None).

    If `format_filter` is given (a format string, or a list of them), only
    tournaments with a matching `format` are listed.
    """
    tournaments = fetch_tournaments(sb)
    if format_filter:
        allowed = {format_filter} if isinstance(format_filter, str) else set(format_filter)
        tournaments = [t for t in tournaments if t.get("format") in allowed]
    if not tournaments:
        st.warning("Ainda não existem torneios deste formato. Cria um no separador **Torneios**.")
        return None
    labels = [tournament_label(t) for t in tournaments]
    label_to_t = {tournament_label(t): t for t in tournaments}
    selected = st.selectbox(label, labels, key=key)
    return label_to_t[selected]


def fetch_streetball_state(tournament_id):
    res = (
        sb.table("tournament_streetball")
        .select("*")
        .eq("tournament_id", tournament_id)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def ensure_streetball_state(tournament_id):
    state = fetch_streetball_state(tournament_id)
    if state:
        return state
    res = sb.table("tournament_streetball").insert(
        {"tournament_id": tournament_id}
    ).execute()
    return res.data[0]


def round_label_for(num_matches: int) -> str:
    """Human label for a knockout round given how many matches it has."""
    return {
        1: "Final",
        2: "Meias-finais",
        4: "Quartos de final",
        8: "Oitavos de final",
        16: "Dezasseis-avos",
    }.get(num_matches, f"Ronda de {num_matches} jogos")


def date_or_none(s):
    """Parse a 'YYYY-MM-DD' string into a date, or None."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def advance_winner(sb, match, winner_id):
    """Push the winner of a knockout match into the correct slot of its next match."""
    nm_id = match.get("next_match_id")
    if not nm_id:
        return
    # feeders at even bracket positions fill team_a, odd fill team_b
    slot = "team_a_id" if (match.get("bracket_position") or 0) % 2 == 0 else "team_b_id"
    sb.table("tournament_matches").update({slot: winner_id}).eq("id", nm_id).execute()


def generate_bracket(sb, tournament, team_ids):
    """Create a single-elimination bracket. Extra teams beyond a power of two get byes.

    Returns the number of matches created.
    """
    n = len(team_ids)
    size = 1
    while size < n:
        size *= 2
    rounds = int(math.log2(size))
    slots = list(team_ids) + [None] * (size - n)
    admin = st.session_state.get("username")

    # 1) create empty matches, round by round (round 1 = first round, last = final)
    round_match_ids = {}
    created = 0
    for r in range(1, rounds + 1):
        num = size // (2 ** r)
        label = round_label_for(num)
        ids = []
        for pos in range(num):
            res = sb.table("tournament_matches").insert({
                "tournament_id": tournament["id"],
                "stage": "knockout",
                "round": r,
                "round_label": label,
                "bracket_position": pos,
                "court_id": tournament.get("court_id"),
                "status": "scheduled",
                "admin_created_by": admin,
            }).execute()
            ids.append(res.data[0]["id"])
            created += 1
        round_match_ids[r] = ids

    # 2) link each match to the next round's match
    for r in range(1, rounds):
        for pos, mid in enumerate(round_match_ids[r]):
            sb.table("tournament_matches").update(
                {"next_match_id": round_match_ids[r + 1][pos // 2]}
            ).eq("id", mid).execute()

    # 3) seat teams into round 1, auto-resolving byes
    for pos, mid in enumerate(round_match_ids[1]):
        a, b = slots[2 * pos], slots[2 * pos + 1]
        update = {"team_a_id": a, "team_b_id": b}
        if (a is None) ^ (b is None):  # exactly one team -> bye
            winner = a or b
            update["winner_team_id"] = winner
            update["status"] = "completed"
            if rounds >= 2:
                nxt = round_match_ids[2][pos // 2]
                slot = "team_a_id" if pos % 2 == 0 else "team_b_id"
                sb.table("tournament_matches").update({slot: winner}).eq("id", nxt).execute()
        sb.table("tournament_matches").update(update).eq("id", mid).execute()

    return created


# =======================================================================
# TABS
# =======================================================================
tab_t, tab_e, tab_g, tab_j, tab_rbf = st.tabs(
    ["🏆 Torneios", "👥 Equipas", "🔀 Grupos & Sorteio", "🏀 Jogos", "🕺 Roda Bota Fora"]
)

# =======================================================================
# TAB 1: Tournaments (create / edit)
# =======================================================================
with tab_t:
    sub_create, sub_edit = st.tabs(["Criar", "Editar"])

    courts = fetch_courts(sb)
    court_labels = ["— Sem campo —"] + [court_label(c) for c in courts]
    court_label_to_id = {court_label(c): c["id"] for c in courts}

    # ---- Create ----
    with sub_create:
        st.subheader("Criar Torneio")
        with st.form("create_tournament_form"):
            col1, col2 = st.columns(2)
            with col1:
                name_in = st.text_input("Nome *")
                fmt_in = st.selectbox(
                    "Formato *",
                    list(FORMATS.keys()),
                    format_func=lambda k: FORMATS[k],
                )
                team_size_in = st.number_input(
                    "Tamanho da equipa (1 = 1x1, 3 = 3x3, …) *", 1, 15, 5, step=1
                )
                court_sel = st.selectbox("Campo", court_labels, key="create_t_court")
            with col2:
                status_in = st.selectbox("Estado *", STATUSES, index=0)
                max_teams_in = st.number_input(
                    "Máx. equipas (0 = sem limite)", 0, 256, 0, step=1
                )
                start_in = st.date_input("Data de início", value=None)
                end_in = st.date_input("Data de fim", value=None)
                price_in = st.number_input(
                    "Preço por equipa (€, 0 = grátis)", 0.0, 100000.0, 0.0, step=5.0
                )

            image_file_in = st.file_uploader(
                "Imagem do torneio (opcional)", type=["jpg", "jpeg", "png"]
            )
            desc_in = st.text_area("Descrição")

            st.markdown("**Configuração da fase de grupos** (só para o formato com grupos)")
            gc1, gc2, gc3, gc4 = st.columns(4)
            with gc1:
                pts_win = st.number_input("Pontos vitória", 0, 10, 2, step=1)
            with gc2:
                pts_draw = st.number_input("Pontos empate", 0, 10, 1, step=1)
            with gc3:
                pts_loss = st.number_input("Pontos derrota", 0, 10, 1, step=1)
            with gc4:
                advancing = st.number_input("Apuram por grupo", 1, 16, 2, step=1)

            submitted = st.form_submit_button("Criar Torneio")

        if submitted:
            if not name_in.strip():
                st.error("Nome é obrigatório.")
                st.stop()

            payload = {
                "name": name_in.strip(),
                "description": desc_in.strip() or None,
                "price_per_team": float(price_in) or None,
                "format": fmt_in,
                "team_size": int(team_size_in),
                "status": status_in,
                "max_teams": int(max_teams_in) or None,
                "start_date": start_in.isoformat() if start_in else None,
                "end_date": end_in.isoformat() if end_in else None,
                "points_win": int(pts_win),
                "points_draw": int(pts_draw),
                "points_loss": int(pts_loss),
                "teams_advancing_per_group": int(advancing),
                "court_id": court_label_to_id.get(court_sel),
                "admin_created_by": st.session_state.get("username"),
            }
            try:
                res = sb.table("tournaments").insert(payload).execute()
                tournament_id = res.data[0]["id"]
                image_url = None
                if image_file_in is not None:
                    with st.spinner("A carregar imagem..."):
                        urls = upload_images_to_storage(
                            sb, [image_file_in], tournament_id,
                            bucket_name=TOURNAMENT_IMAGES_BUCKET,
                        )
                    if urls:
                        image_url = urls[0]
                        sb.table("tournaments").update(
                            {"image_url": image_url}
                        ).eq("id", tournament_id).execute()
                st.success(f"Torneio criado ✅ (ID: {tournament_id})")

                if float(price_in) > 0:
                    try:
                        with st.spinner("A criar produto no Stripe..."):
                            fields = sync_tournament_stripe(
                                sb, tournament_id, name_in.strip(),
                                float(price_in), image_url,
                            )
                        st.success("Produto Stripe criado ✅")
                        if fields.get("stripe_payment_link"):
                            st.caption(f"Link de pagamento: {fields['stripe_payment_link']}")
                    except Exception as e:
                        st.warning(
                            f"Torneio criado, mas falhou a criação do produto Stripe: {e}. "
                            "Podes voltar a guardar o torneio para tentar de novo."
                        )
            except Exception as e:
                st.error(f"Erro ao criar torneio: {e}")

    # ---- Edit ----
    with sub_edit:
        st.subheader("Editar Torneio")
        t = tournament_selectbox("edit_t_select")
        if t:
            st.info(f"A editar: **{t['name']}** (ID: {t['id']})")
            with st.form("edit_tournament_form"):
                col1, col2 = st.columns(2)
                with col1:
                    name_e = st.text_input("Nome *", value=t.get("name", ""))
                    fmt_e = st.selectbox(
                        "Formato *",
                        list(FORMATS.keys()),
                        index=list(FORMATS.keys()).index(t.get("format", "knockout")),
                        format_func=lambda k: FORMATS[k],
                    )
                    team_size_e = st.number_input(
                        "Tamanho da equipa *", 1, 15, int(t.get("team_size") or 5), step=1
                    )
                    cur_court = next(
                        (court_label(c) for c in courts if c["id"] == t.get("court_id")),
                        "— Sem campo —",
                    )
                    court_e = st.selectbox(
                        "Campo", court_labels,
                        index=court_labels.index(cur_court),
                        key="edit_t_court",
                    )
                with col2:
                    status_e = st.selectbox(
                        "Estado *", STATUSES, index=STATUSES.index(t.get("status", "draft"))
                    )
                    max_teams_e = st.number_input(
                        "Máx. equipas (0 = sem limite)", 0, 256,
                        int(t.get("max_teams") or 0), step=1
                    )
                    start_e = st.date_input(
                        "Data de início",
                        value=date_or_none(t.get("start_date")),
                    )
                    end_e = st.date_input(
                        "Data de fim",
                        value=date_or_none(t.get("end_date")),
                    )
                    price_e = st.number_input(
                        "Preço por equipa (€, 0 = grátis)", 0.0, 100000.0,
                        float(t.get("price_per_team") or 0.0), step=5.0
                    )

                if t.get("image_url"):
                    st.image(t["image_url"], width=200, caption="Imagem atual")
                image_file_e = st.file_uploader(
                    "Substituir imagem (opcional)", type=["jpg", "jpeg", "png"]
                )
                desc_e = st.text_area("Descrição", value=t.get("description", "") or "")

                gc1, gc2, gc3, gc4 = st.columns(4)
                with gc1:
                    pts_win_e = st.number_input("Pontos vitória", 0, 10, int(t.get("points_win") or 2), step=1)
                with gc2:
                    pts_draw_e = st.number_input("Pontos empate", 0, 10, int(t.get("points_draw") or 1), step=1)
                with gc3:
                    pts_loss_e = st.number_input("Pontos derrota", 0, 10, int(t.get("points_loss") or 1), step=1)
                with gc4:
                    advancing_e = st.number_input("Apuram por grupo", 1, 16, int(t.get("teams_advancing_per_group") or 2), step=1)

                submitted_e = st.form_submit_button("Atualizar Torneio")

            if submitted_e:
                if not name_e.strip():
                    st.error("Nome é obrigatório.")
                    st.stop()
                payload = {
                    "name": name_e.strip(),
                    "description": desc_e.strip() or None,
                    "price_per_team": float(price_e) or None,
                    "format": fmt_e,
                    "team_size": int(team_size_e),
                    "status": status_e,
                    "max_teams": int(max_teams_e) or None,
                    "start_date": start_e.isoformat() if start_e else None,
                    "end_date": end_e.isoformat() if end_e else None,
                    "points_win": int(pts_win_e),
                    "points_draw": int(pts_draw_e),
                    "points_loss": int(pts_loss_e),
                    "teams_advancing_per_group": int(advancing_e),
                    "court_id": court_label_to_id.get(court_e),
                    "admin_created_by": st.session_state.get("username"),
                }
                if image_file_e is not None:
                    with st.spinner("A carregar imagem..."):
                        urls = upload_images_to_storage(
                            sb, [image_file_e], t["id"],
                            bucket_name=TOURNAMENT_IMAGES_BUCKET,
                        )
                    if urls:
                        payload["image_url"] = urls[0]
                try:
                    sb.table("tournaments").update(payload).eq("id", t["id"]).execute()
                    st.success("Torneio atualizado ✅")
                    try:
                        with st.spinner("A sincronizar com o Stripe..."):
                            sync_tournament_stripe(
                                sb, t["id"], name_e.strip(), float(price_e),
                                payload.get("image_url") or t.get("image_url"),
                            )
                    except Exception as e:
                        st.warning(f"Falhou a sincronização com o Stripe: {e}")
                except Exception as e:
                    st.error(f"Erro ao atualizar torneio: {e}")

            st.divider()
            if st.button("🗑️ Eliminar torneio", type="secondary", key="del_t"):
                try:
                    sb.table("tournaments").delete().eq("id", t["id"]).execute()
                    st.success("Torneio eliminado. Recarrega a página.")
                except Exception as e:
                    st.error(f"Erro ao eliminar: {e}")

# =======================================================================
# TAB 2: Teams & rosters
# =======================================================================
with tab_e:
    st.subheader("Equipas & Plantéis")
    t = tournament_selectbox("teams_t_select")
    if t:
        # ---- Add team ----
        with st.form("add_team_form"):
            st.markdown("**Adicionar equipa**")
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1:
                team_name_in = st.text_input("Nome da equipa *")
            with c2:
                logo_in = st.text_input("Logo URL (opcional)")
            with c3:
                seed_in = st.number_input("Seed (opcional)", 0, 256, 0, step=1)
            add_team = st.form_submit_button("Adicionar equipa")

        if add_team:
            if not team_name_in.strip():
                st.error("Nome da equipa é obrigatório.")
            else:
                try:
                    sb.table("tournament_teams").insert({
                        "tournament_id": t["id"],
                        "name": team_name_in.strip(),
                        "logo_url": logo_in.strip() or None,
                        "seed": int(seed_in) or None,
                        "admin_created_by": st.session_state.get("username"),
                    }).execute()
                    st.success("Equipa adicionada ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao adicionar equipa: {e}")

        st.divider()
        teams = fetch_teams(t["id"])
        if not teams:
            st.info("Ainda não há equipas neste torneio.")
        else:
            profiles = fetch_profiles(sb)
            profile_opts = ["— Convidado (sem conta) —"] + [profile_label(p) for p in profiles]
            plabel_to_id = {profile_label(p): p["id"] for p in profiles}

            price = t.get("price_per_team")
            if price:
                paid_count = sum(1 for tm in teams if tm.get("is_paid"))
                st.caption(
                    f"💶 Preço por equipa: **{float(price):.2f} €**  ·  "
                    f"Pagas: **{paid_count}/{len(teams)}**"
                )

            for team in teams:
                paid_badge = "💶 Pago" if team.get("is_paid") else "⚠️ Por pagar"
                with st.expander(f"🛡️ {team_label(team)}  ·  {paid_badge}", expanded=False):
                    pc1, pc2 = st.columns([3, 1])
                    pc1.write("💶 **Pago**" if team.get("is_paid") else "⚠️ **Por pagar**")
                    if team.get("is_paid"):
                        if pc2.button("Marcar por pagar", key=f"unpaid_{team['id']}"):
                            sb.table("tournament_teams").update(
                                {"is_paid": False, "paid_at": None}
                            ).eq("id", team["id"]).execute()
                            st.rerun()
                    else:
                        if pc2.button("Marcar como pago", key=f"paid_{team['id']}"):
                            sb.table("tournament_teams").update(
                                {"is_paid": True, "paid_at": datetime.now(timezone.utc).isoformat()}
                            ).eq("id", team["id"]).execute()
                            st.rerun()
                    members = (
                        sb.table("tournament_team_members")
                        .select("*")
                        .eq("team_id", team["id"])
                        .order("created_at")
                        .execute()
                        .data
                        or []
                    )
                    # name lookup for profile members
                    pid_to_name = {p["id"]: p.get("display_name") for p in profiles}
                    if members:
                        for m in members:
                            who = pid_to_name.get(m.get("profile_id")) or m.get("player_name") or "—"
                            tags = []
                            if m.get("is_captain"):
                                tags.append("©️ Capitão")
                            if m.get("jersey_number") is not None:
                                tags.append(f"#{m['jersey_number']}")
                            if not m.get("profile_id"):
                                tags.append("convidado")
                            meta = f"  ·  {' · '.join(tags)}" if tags else ""
                            mc1, mc2 = st.columns([5, 1])
                            mc1.write(f"- **{who}**{meta}")
                            if mc2.button("Remover", key=f"rm_{m['id']}"):
                                sb.table("tournament_team_members").delete().eq("id", m["id"]).execute()
                                st.rerun()
                    else:
                        st.caption("Sem jogadores.")

                    with st.form(f"add_member_{team['id']}"):
                        st.markdown("**Adicionar jogador**")
                        ac1, ac2, ac3 = st.columns([3, 1, 1])
                        with ac1:
                            prof_sel = st.selectbox(
                                "Jogador (conta) ou convidado", profile_opts,
                                key=f"prof_{team['id']}"
                            )
                            guest_name = st.text_input(
                                "Nome do convidado (se sem conta)", key=f"guest_{team['id']}"
                            )
                        with ac2:
                            jersey = st.number_input("Nº", 0, 99, 0, step=1, key=f"jersey_{team['id']}")
                        with ac3:
                            captain = st.checkbox("Capitão", key=f"cap_{team['id']}")
                        add_member = st.form_submit_button("Adicionar jogador")

                    if add_member:
                        profile_id = plabel_to_id.get(prof_sel)  # None if guest option
                        payload = {
                            "team_id": team["id"],
                            "profile_id": profile_id,
                            "player_name": guest_name.strip() or None if not profile_id else None,
                            "jersey_number": int(jersey) or None,
                            "is_captain": captain,
                        }
                        if not profile_id and not payload["player_name"]:
                            st.error("Escolhe um jogador com conta ou indica o nome do convidado.")
                        else:
                            try:
                                sb.table("tournament_team_members").insert(payload).execute()
                                st.success("Jogador adicionado ✅")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao adicionar jogador: {e}")

                    st.divider()
                    if st.button("🗑️ Eliminar equipa", key=f"del_team_{team['id']}"):
                        sb.table("tournament_teams").delete().eq("id", team["id"]).execute()
                        st.rerun()

# =======================================================================
# TAB 3: Groups & draw
# =======================================================================
with tab_g:
    st.subheader("Grupos & Sorteio")
    t = tournament_selectbox("groups_t_select", format_filter="group_then_knockout")
    if t:
        # Create group
        with st.form("add_group_form"):
            gname = st.text_input("Nome do grupo (ex.: Grupo A) *")
            add_group = st.form_submit_button("Criar grupo")
        if add_group:
            if not gname.strip():
                st.error("Nome do grupo é obrigatório.")
            else:
                try:
                    sb.table("tournament_groups").insert({
                        "tournament_id": t["id"],
                        "name": gname.strip(),
                    }).execute()
                    st.success("Grupo criado ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao criar grupo: {e}")

        st.divider()
        groups = fetch_groups(t["id"])
        teams = fetch_teams(t["id"])
        if not groups:
            st.info("Ainda não há grupos.")
        elif not teams:
            st.info("Cria equipas primeiro no separador *Equipas*.")
        else:
            gid_to_name = {g["id"]: g["name"] for g in groups}
            group_opts = ["— Sem grupo —"] + [g["name"] for g in groups]
            gname_to_id = {g["name"]: g["id"] for g in groups}

            st.markdown("**Atribuir equipas a grupos**")
            for team in teams:
                cur = gid_to_name.get(team.get("group_id"), "— Sem grupo —")
                sel = st.selectbox(
                    team["name"], group_opts,
                    index=group_opts.index(cur),
                    key=f"grp_{team['id']}",
                )
                new_gid = gname_to_id.get(sel)
                if new_gid != team.get("group_id"):
                    sb.table("tournament_teams").update(
                        {"group_id": new_gid}
                    ).eq("id", team["id"]).execute()
                    st.rerun()

            st.divider()
            st.markdown("**Gerar jogos da fase de grupos** (todos-contra-todos por grupo)")
            if st.button("⚙️ Gerar jogos de grupo"):
                created = 0
                for g in groups:
                    gteams = [t2 for t2 in teams if t2.get("group_id") == g["id"]]
                    for i in range(len(gteams)):
                        for j in range(i + 1, len(gteams)):
                            sb.table("tournament_matches").insert({
                                "tournament_id": t["id"],
                                "stage": "group",
                                "group_id": g["id"],
                                "team_a_id": gteams[i]["id"],
                                "team_b_id": gteams[j]["id"],
                                "court_id": t.get("court_id"),
                                "status": "scheduled",
                                "admin_created_by": st.session_state.get("username"),
                            }).execute()
                            created += 1
                st.success(f"{created} jogo(s) de grupo criado(s) ✅")

# =======================================================================
# TAB 4: Matches (scores, standings, bracket)
# =======================================================================
with tab_j:
    st.subheader("Jogos")
    t = tournament_selectbox(
        "matches_t_select", format_filter=["knockout", "group_then_knockout"]
    )
    if t:
        teams = fetch_teams(t["id"])
        team_by_id = {tm["id"]: tm for tm in teams}

        def tname(tid):
            tm = team_by_id.get(tid)
            return tm["name"] if tm else "— TBD —"

        # ---- Standings (group stage) ----
        if t.get("format") == "group_then_knockout":
            st.markdown("### 📊 Classificações de grupo")
            standings = (
                sb.table("tournament_group_standings")
                .select("*")
                .eq("tournament_id", t["id"])
                .order("group_id")
                .order("standing_points", desc=True)
                .order("point_diff", desc=True)
                .execute()
                .data
                or []
            )
            groups = fetch_groups(t["id"])
            gid_to_name = {g["id"]: g["name"] for g in groups}
            if standings:
                by_group = {}
                for row in standings:
                    by_group.setdefault(row["group_id"], []).append(row)
                for gid, rows in by_group.items():
                    st.markdown(f"**{gid_to_name.get(gid, 'Grupo')}**")
                    st.dataframe(
                        [
                            {
                                "Equipa": r["team_name"],
                                "J": r["played"],
                                "V": r["wins"],
                                "E": r["draws"],
                                "D": r["losses"],
                                "PM": r["points_for"],
                                "PS": r["points_against"],
                                "Dif": r["point_diff"],
                                "Pts": r["standing_points"],
                            }
                            for r in rows
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )
            else:
                st.caption("Sem jogos de grupo concluídos ainda.")
            st.divider()

        # ---- Generate knockout bracket ----
        st.markdown("### 🏟️ Gerar quadro de eliminatórias")
        st.caption(
            "Seleciona as equipas (pela ordem de seeding desejada). "
            "Equipas a mais para uma potência de 2 recebem 'bye' automático."
        )
        with st.form("gen_bracket_form"):
            team_opts = [team_label(tm) for tm in teams]
            tlabel_to_id = {team_label(tm): tm["id"] for tm in teams}
            chosen = st.multiselect("Equipas no quadro", team_opts)
            gen = st.form_submit_button("⚙️ Gerar quadro")

        if gen:
            ids = [tlabel_to_id[c] for c in chosen]
            if len(ids) < 2:
                st.error("Escolhe pelo menos 2 equipas.")
            else:
                try:
                    n_created = generate_bracket(sb, t, ids)
                    st.success(f"Quadro gerado com {n_created} jogo(s) ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao gerar quadro: {e}")

        st.divider()

        # ---- Add single match manually ----
        with st.expander("➕ Adicionar jogo manualmente"):
            with st.form("add_match_form"):
                stage = st.selectbox("Fase", ["group", "knockout"])
                groups = fetch_groups(t["id"])
                group_id = None
                if stage == "group" and groups:
                    gsel = st.selectbox("Grupo", [g["name"] for g in groups])
                    group_id = next(g["id"] for g in groups if g["name"] == gsel)
                team_opts2 = ["— TBD —"] + [team_label(tm) for tm in teams]
                tlabel_to_id2 = {team_label(tm): tm["id"] for tm in teams}
                ca, cb = st.columns(2)
                with ca:
                    a_sel = st.selectbox("Equipa A", team_opts2, key="man_a")
                with cb:
                    b_sel = st.selectbox("Equipa B", team_opts2, key="man_b")
                rlabel = st.text_input("Etiqueta da ronda (ex.: Final)")
                add_match = st.form_submit_button("Adicionar jogo")
            if add_match:
                try:
                    sb.table("tournament_matches").insert({
                        "tournament_id": t["id"],
                        "stage": stage,
                        "group_id": group_id,
                        "team_a_id": tlabel_to_id2.get(a_sel),
                        "team_b_id": tlabel_to_id2.get(b_sel),
                        "round_label": rlabel.strip() or None,
                        "court_id": t.get("court_id"),
                        "status": "scheduled",
                        "admin_created_by": st.session_state.get("username"),
                    }).execute()
                    st.success("Jogo adicionado ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao adicionar jogo: {e}")

        # ---- List matches + score entry ----
        st.markdown("### Resultados")
        matches = fetch_matches(t["id"])
        if not matches:
            st.info("Ainda não há jogos.")
        for m in matches:
            stage_txt = "Grupo" if m["stage"] == "group" else (m.get("round_label") or "Eliminatória")
            with st.container(border=True):
                st.markdown(
                    f"**{stage_txt}** — {tname(m.get('team_a_id'))} 🆚 {tname(m.get('team_b_id'))}  ·  `{m['status']}`"
                )
                with st.form(f"score_{m['id']}"):
                    sc1, sc2, sc3 = st.columns([1, 1, 2])
                    with sc1:
                        sa = st.number_input(
                            f"{tname(m.get('team_a_id'))}", 0, 500,
                            int(m["score_a"]) if m.get("score_a") is not None else 0,
                            step=1, key=f"sa_{m['id']}"
                        )
                    with sc2:
                        sb_score = st.number_input(
                            f"{tname(m.get('team_b_id'))}", 0, 500,
                            int(m["score_b"]) if m.get("score_b") is not None else 0,
                            step=1, key=f"sb_{m['id']}"
                        )
                    with sc3:
                        mstatus = st.selectbox(
                            "Estado", MATCH_STATUSES,
                            index=MATCH_STATUSES.index(m["status"]),
                            key=f"ms_{m['id']}"
                        )
                    save = st.form_submit_button("Guardar resultado")
                if save:
                    winner = None
                    if mstatus == "completed":
                        if sa > sb_score:
                            winner = m.get("team_a_id")
                        elif sb_score > sa:
                            winner = m.get("team_b_id")
                    try:
                        sb.table("tournament_matches").update({
                            "score_a": int(sa),
                            "score_b": int(sb_score),
                            "status": mstatus,
                            "winner_team_id": winner,
                        }).eq("id", m["id"]).execute()

                        # advance winner in the knockout bracket
                        if winner and m.get("next_match_id"):
                            advance_winner(sb, m, winner)
                        st.success("Resultado guardado ✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao guardar: {e}")

# =======================================================================
# TAB 5: Roda Bota Fora (streetball) — winner, challenger, queue & eliminated
# =======================================================================
with tab_rbf:
    st.subheader("Roda Bota Fora")
    t = tournament_selectbox("rbf_t_select", format_filter="streetball")
    if t:
        teams = fetch_teams(t["id"])
        if not teams:
            st.info("Este torneio ainda não tem equipas. Adiciona equipas no separador **Equipas**.")
        else:
            state = ensure_streetball_state(t["id"])
            eliminated_ids = set(state.get("eliminated_team_ids") or [])
            current_winner_id = state.get("current_winner_team_id")
            current_challenger_id = state.get("current_challenger_team_id")
            queue_ids = list(state.get("challenger_queue_team_ids") or [])
            team_by_id = {tm["id"]: tm for tm in teams}
            is_completed = t.get("status") == "completed"

            def team_name(team_id):
                tm = team_by_id.get(team_id)
                return tm["name"] if tm else "?"

            def save_state(payload):
                sb.table("tournament_streetball").update(payload).eq("id", state["id"]).execute()

            if current_winner_id and current_winner_id in team_by_id:
                if is_completed:
                    st.success(f"🏆 Vencedor final: **{team_name(current_winner_id)}**")
                else:
                    st.success(f"🏆 Vencedor atual: **{team_name(current_winner_id)}**")
            else:
                st.info("Ainda não há vencedor atual definido.")

            active_teams = [tm for tm in teams if tm["id"] not in eliminated_ids]

            if is_completed:
                st.caption(
                    "🔒 Este torneio está marcado como **concluído** — o vencedor atual é o "
                    "vencedor final e já não pode ser alterado aqui."
                )
            else:
                st.divider()
                st.markdown("**Definir vencedor atual**")
                if active_teams:
                    winner_opts = [team_label(tm) for tm in active_teams]
                    wlabel_to_id = {team_label(tm): tm["id"] for tm in active_teams}
                    cur_label = next(
                        (team_label(tm) for tm in active_teams if tm["id"] == current_winner_id),
                        winner_opts[0],
                    )
                    winner_sel = st.selectbox(
                        "Equipa vencedora", winner_opts,
                        index=winner_opts.index(cur_label), key="rbf_winner_sel",
                    )
                    if st.button("👑 Guardar vencedor atual"):
                        try:
                            new_winner_id = wlabel_to_id[winner_sel]
                            # a team can't be its own challenger or sit in the queue at the same time
                            new_challenger_id = (
                                None if current_challenger_id == new_winner_id else current_challenger_id
                            )
                            new_queue = [i for i in queue_ids if i != new_winner_id]
                            save_state({
                                "current_winner_team_id": new_winner_id,
                                "current_challenger_team_id": new_challenger_id,
                                "challenger_queue_team_ids": new_queue,
                            })
                            st.success("Vencedor atualizado ✅")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao guardar vencedor: {e}")
                else:
                    st.warning("Todas as equipas foram eliminadas.")

                # -----------------------------------------------------
                # Desafiante atual + resultado do jogo
                # -----------------------------------------------------
                st.divider()
                st.markdown("**Desafiante atual**")
                if current_challenger_id and current_challenger_id in team_by_id:
                    st.write(f"🥊 A defrontar o vencedor: **{team_name(current_challenger_id)}**")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("🏆 Desafiante venceu", key="rbf_challenger_wins"):
                        try:
                            new_eliminated = list(eliminated_ids)
                            if current_winner_id:
                                new_eliminated.append(current_winner_id)
                            save_state({
                                "current_winner_team_id": current_challenger_id,
                                "current_challenger_team_id": queue_ids[0] if queue_ids else None,
                                "challenger_queue_team_ids": queue_ids[1:],
                                "eliminated_team_ids": new_eliminated,
                            })
                            st.success("Resultado registado ✅")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao registar resultado: {e}")
                    if cc2.button("👑 Vencedor manteve-se", key="rbf_winner_stays"):
                        try:
                            new_eliminated = list(eliminated_ids) + [current_challenger_id]
                            save_state({
                                "current_challenger_team_id": queue_ids[0] if queue_ids else None,
                                "challenger_queue_team_ids": queue_ids[1:],
                                "eliminated_team_ids": new_eliminated,
                            })
                            st.success("Resultado registado ✅")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao registar resultado: {e}")
                elif queue_ids:
                    st.caption("Sem desafiante em jogo — há equipas à espera na fila.")
                    if st.button("▶️ Chamar próximo da fila", key="rbf_pull_next"):
                        try:
                            save_state({
                                "current_challenger_team_id": queue_ids[0],
                                "challenger_queue_team_ids": queue_ids[1:],
                            })
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao chamar próxima equipa: {e}")
                else:
                    st.caption("Sem desafiante definido e a fila está vazia.")

                # -----------------------------------------------------
                # Fila de desafiantes (ordem aleatória, guardada ao baralhar)
                # -----------------------------------------------------
                st.divider()
                st.markdown("**Fila de desafiantes**")
                shuffle_pool = [
                    tm["id"] for tm in active_teams
                    if tm["id"] != current_winner_id and tm["id"] != current_challenger_id
                ]
                if st.button("🎲 Baralhar fila", key="rbf_shuffle_queue", disabled=not shuffle_pool):
                    try:
                        shuffled = list(shuffle_pool)
                        random.shuffle(shuffled)
                        save_state({"challenger_queue_team_ids": shuffled})
                        st.success("Fila baralhada ✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao baralhar fila: {e}")

                if queue_ids:
                    for idx, team_id in enumerate(queue_ids):
                        if team_id not in team_by_id:
                            continue
                        qc1, qc2 = st.columns([5, 1])
                        qc1.write(f"**{idx + 1}.** {team_name(team_id)}")
                        if qc2.button("🗑️", key=f"rbf_q_remove_{team_id}"):
                            new_queue = [i for i in queue_ids if i != team_id]
                            save_state({"challenger_queue_team_ids": new_queue})
                            st.rerun()
                else:
                    st.caption("A fila está vazia. Usa **🎲 Baralhar fila** para gerar uma ordem aleatória.")

                # -----------------------------------------------------
                # Lista de equipas (eliminação/reposição manual)
                # -----------------------------------------------------
                st.divider()
                st.markdown("**Equipas**")
                for tm in teams:
                    is_eliminated = tm["id"] in eliminated_ids
                    is_winner = tm["id"] == current_winner_id
                    is_challenger = tm["id"] == current_challenger_id
                    queue_pos = queue_ids.index(tm["id"]) + 1 if tm["id"] in queue_ids else None
                    if is_winner:
                        badge = "🏆 Vencedor atual"
                    elif is_challenger:
                        badge = "🥊 Desafiante atual"
                    elif queue_pos:
                        badge = f"🕒 Fila #{queue_pos}"
                    elif is_eliminated:
                        badge = "❌ Eliminado"
                    else:
                        badge = "— Disponível —"

                    c1, c2 = st.columns([4, 1])
                    c1.write(f"**{team_label(tm)}**  ·  {badge}")
                    if is_eliminated:
                        if c2.button("↩️ Repor", key=f"rbf_restore_{tm['id']}"):
                            new_elim = [i for i in eliminated_ids if i != tm["id"]]
                            try:
                                save_state({"eliminated_team_ids": new_elim})
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao repor equipa: {e}")
                    else:
                        if c2.button(
                            "❌ Eliminar", key=f"rbf_elim_{tm['id']}",
                            disabled=is_winner or is_challenger,
                        ):
                            new_elim = list(eliminated_ids) + [tm["id"]]
                            new_queue = [i for i in queue_ids if i != tm["id"]]
                            try:
                                save_state({
                                    "eliminated_team_ids": new_elim,
                                    "challenger_queue_team_ids": new_queue,
                                })
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao eliminar equipa: {e}")
